#define _CRT_SECURE_NO_WARNINGS
#include "gs_static_recognition.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <windows.h>

gs_ai_status_t gs_round8_execute(const gs_int8_model_t *, const int8_t *, size_t,
    int8_t *, size_t, int8_t *, size_t);
gs_ai_status_t gs_round8_execute_progress(const gs_int8_model_t *, const int8_t *, size_t,
    int8_t *, size_t, int8_t *, size_t, gs_int8_progress_fn, void *);
gs_ai_status_t gs_packed_execute(const gs_int8_model_t *, const int8_t *, size_t,
    int8_t *, size_t, int8_t *, size_t);
int32_t gs_round8_scale(int32_t, int32_t, int8_t);
int32_t gs_candidate_scale(int32_t, int32_t, int8_t);
int32_t gs_candidate_dot4(const int8_t *, const int8_t *, int32_t);
int8_t gs_candidate_relu_finish(int32_t,int32_t,int8_t,int8_t);
int8_t gs_candidate_negative_relu(int32_t,int32_t,int8_t);
static int8_t input[9216], old_workspace[73728], new_workspace[73728], packed_workspace[73728];
static int8_t old_output[36864], new_output[36864], packed_output[36864];
static int8_t layer_input[36864];
static uint32_t seed = UINT32_C(0x183294af), callbacks;
static uint32_t random_word(void)
{ seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; return seed; }
static bool progress(void *context, size_t layer, uint32_t count)
{ (void)context; assert(layer < 29 && count != 0); ++callbacks; return true; }
static bool aborting(void *context, size_t layer, uint32_t count)
{ (void)context; (void)layer; assert(count == 64); return false; }
typedef struct {
    const gs_int8_model_t *model;const int8_t *input;int8_t *output,*workspace;
    unsigned invoked;
} reentrant_context_t;
static bool reentrant_progress(void *context,size_t layer,uint32_t count)
{
    reentrant_context_t *r=context;(void)layer;assert(count!=0U);
    if(!r->invoked){
        r->invoked=1U;
        assert(gs_int8_execute(r->model,r->input,r->model->input_size,r->output,r->model->output_size,
            r->workspace,73728U)==GS_AI_OK);
    }
    return true;
}
static void compare(const gs_int8_model_t *model, const int8_t *data)
{
    assert(gs_round8_execute(model, data, model->input_size, old_output, model->output_size,
        old_workspace, sizeof old_workspace) == GS_AI_OK);
    assert(gs_int8_execute(model, data, model->input_size, new_output, model->output_size,
        new_workspace, sizeof new_workspace) == GS_AI_OK);
    assert(gs_packed_execute(model, data, model->input_size, packed_output, model->output_size,
        packed_workspace, sizeof packed_workspace) == GS_AI_OK);
    assert(memcmp(old_output, new_output, model->output_size) == 0);
    assert(memcmp(old_output, packed_output, model->output_size) == 0);
}
static void scale_and_packing(void)
{
    const int32_t values[] = {INT32_MIN, INT32_MIN+1, -1073741825, -1073741824,
        -65537, -32769, -129, -128, -65, -64, -33, -32, -17, -16, -9, -8,
        -5,-4,-3,-2,-1,0,1,2,3,4,5,8,9,16,17,32,33,64,65,127,128,
        32768,65536,1073741823,1073741824,INT32_MAX-1,INT32_MAX};
    const int32_t multipliers[] = {0,1,2,1073741823,1073741824,1073741825,INT32_MAX};
    size_t i, m; int shift; unsigned trial;
    for (i=0; i<sizeof values/sizeof values[0]; ++i) {
        for (m=0; m<sizeof multipliers/sizeof multipliers[0]; ++m) {
            for (shift=-31; shift<=30; ++shift) {
                assert(gs_candidate_scale(values[i],multipliers[m],(int8_t)shift) ==
                    gs_round8_scale(values[i],multipliers[m],(int8_t)shift));
                int32_t expected=gs_round8_scale(values[i],multipliers[m],(int8_t)shift);
                if(expected<0)expected=0;if(expected>255)expected=255;
                assert(gs_candidate_relu_finish(values[i],multipliers[m],(int8_t)shift,127)==expected-128);
                if(shift<0)assert(gs_candidate_negative_relu(values[i],multipliers[m],(int8_t)shift)==expected-128);
            }
        }
    }
    for (trial=0; trial<200000; ++trial) {
        int32_t v=(int32_t)random_word(), multiplier=(int32_t)(random_word() & INT32_MAX);
        shift=(int)(random_word()%62U)-31;
        assert(gs_candidate_scale(v,multiplier,(int8_t)shift) == gs_round8_scale(v,multiplier,(int8_t)shift));
        int32_t expected=gs_round8_scale(v,multiplier,(int8_t)shift);
        int8_t maximum=(int8_t)(trial&255U);
        if(expected<0)expected=0;if(expected>(int32_t)maximum+128)expected=(int32_t)maximum+128;
        assert(gs_candidate_relu_finish(v,multiplier,(int8_t)shift,maximum)==expected-128);
        shift=-(int)(1U+trial%31U);expected=gs_round8_scale(v,multiplier,(int8_t)shift);
        if(expected<0)expected=0;if(expected>255)expected=255;
        assert(gs_candidate_negative_relu(v,multiplier,(int8_t)shift)==expected-128);
    }
    for (trial=0; trial<20000; ++trial) {
        int8_t a[5], b[5]; int32_t sum=12345, expected=sum;
        for (i=0; i<5; ++i) { a[i]=(int8_t)random_word(); b[i]=(int8_t)random_word(); }
        for (i=1; i<5; ++i) { expected += a[i]*b[i]; }
        /* Deliberately byte-offset buffers check packed ordering/alignment. */
        assert(gs_candidate_dot4(a+1,b+1,sum) == expected);
    }
}
static void depthwise_parallel_boundaries(void)
{
    static int8_t weights[9U*257U+1U],shifts[257];
    static int32_t bias[257],multipliers[257];
    const uint16_t channels[]={3,4,8,16,32,128,256,257};
    const int16_t zeros[]={-128,0,127};
    gs_int8_layer_t l={0};gs_int8_model_t m={0};
    for(unsigned i=0;i<sizeof weights;++i)weights[i]=(int8_t)random_word();
    for(unsigned i=0;i<sizeof input;++i)input[i]=(int8_t)random_word();
    for(unsigned i=0;i<257U;++i){bias[i]=(int32_t)i*71-3000;shifts[i]=(int8_t)(-1-(int)(i%31U));multipliers[i]=INT32_MAX-(int32_t)i*2713;}
    l.operation=GS_INT8_DEPTHWISE;l.input_h=l.input_w=l.output_h=l.output_w=5U;
    l.kernel_h=l.kernel_w=3U;l.weights=weights;l.bias=bias;l.multipliers=multipliers;l.shifts=shifts;
    l.output_zero=l.activation_min=-128;l.activation_max=127;
    m.layers=&l;m.layer_count=1U;m.slot_size=36864U;
    for(unsigned c=0;c<sizeof channels/sizeof channels[0];++c)for(unsigned z=0;z<3U;++z){
        l.input_c=l.output_c=channels[c];l.input_zero=zeros[z];m.input_size=m.output_size=25U*channels[c];
        for(unsigned stride=1U;stride<=2U;++stride)for(unsigned pad=0U;pad<=2U;++pad){
            l.stride_h=l.stride_w=(uint16_t)stride;l.pad_h=l.pad_w=(uint16_t)pad;
            compare(&m,input);compare(&m,input+1);l.weights=weights+1;compare(&m,input);l.weights=weights;
        }
        shifts[0]=3;compare(&m,input);shifts[0]=-1; /* mixed positive shift keeps generic finish */
        l.activation_max=81;compare(&m,input);l.activation_max=127;
    }
    l.input_c=l.output_c=4U;m.input_size=m.output_size=100U;l.stride_h=l.stride_w=1U;l.pad_h=l.pad_w=1U;
    memset(weights,0,sizeof weights);bias[0]=INT32_MIN;bias[1]=INT32_MAX;multipliers[2]=0;
    compare(&m,input); /* unsafe cache correction and multiplier0 */
    callbacks=0;
    assert(gs_int8_execute_progress(&m,input,m.input_size,new_output,m.output_size,new_workspace,sizeof new_workspace,progress,NULL)==GS_AI_OK);
    assert(callbacks==2U);memset(new_output,99,m.output_size);
    assert(gs_int8_execute_progress(&m,input,m.input_size,new_output,m.output_size,new_workspace,sizeof new_workspace,aborting,NULL)==GS_AI_BACKEND_FAILURE);
    for(unsigned i=0;i<m.output_size;++i)assert(new_output[i]==99);
    compare(&m,input);
    /* A model can have no output-slot tail or deliberately byte-offset arena.
       Guard exactly the declared workspace extent and preserve caller canaries. */
    {
        static int8_t tight[16000U],offset[73732U];
        size_t sizes[]={m.output_size,m.output_size+7680U-1U,m.output_size+7680U+3U};
        for(unsigned s=0U;s<3U;++s){
            assert(sizes[s]*2U<=sizeof tight-2U);
            m.slot_size=sizes[s];memset(tight,77,sizeof tight);
            assert(gs_int8_execute(&m,input,m.input_size,new_output,m.output_size,tight+1U,m.slot_size*2U)==GS_AI_OK);
            assert(tight[0]==77 && tight[1U+m.slot_size*2U]==77);
            assert(memcmp(old_output,new_output,m.output_size)==0);
        }
        m.slot_size=36864U;memset(offset,77,sizeof offset);
        assert(gs_int8_execute(&m,input,m.input_size,new_output,m.output_size,offset+1U,73728U)==GS_AI_OK);
        assert(offset[0]==77 && offset[73729U]==77 && memcmp(old_output,new_output,m.output_size)==0);
    }
    /* Different invocation's scratch must not corrupt the parent across a
       progress callback. Child has different packed weights and quant params. */
    {
        static int8_t nested_workspace[73728U],child_input[100U],child_output[100U],expected[100U];
        static uint32_t child_weights[9U];
        int32_t child_bias[4]={20000,30000,40000,50000},child_mult[4]={1234567890,1567890123,1789012345,INT32_MAX};
        int8_t child_shifts[4]={-9,-8,-7,-6};
        for(unsigned i=0;i<sizeof weights;++i)weights[i]=(int8_t)random_word();
        bias[0]=-3000;bias[1]=-2929;multipliers[2]=INT32_MAX-5426;
        for(unsigned i=0;i<100U;++i)child_input[i]=(int8_t)(input[i]^0x55);
        for(unsigned i=0;i<9U;++i)child_weights[i]=UINT32_C(0x01020304)+i;
        gs_int8_layer_t child=l;child.weights=(const int8_t *)child_weights;child.bias=child_bias;
        child.multipliers=child_mult;child.shifts=child_shifts;
        gs_int8_model_t nested=m;nested.layers=&child;
        assert(gs_round8_execute(&nested,child_input,100U,expected,100U,nested_workspace,sizeof nested_workspace)==GS_AI_OK);
        compare(&m,input);
        reentrant_context_t context={&nested,child_input,child_output,nested_workspace,0U};
        assert(gs_int8_execute_progress(&m,input,m.input_size,new_output,m.output_size,new_workspace,sizeof new_workspace,
            reentrant_progress,&context)==GS_AI_OK);
        assert(context.invoked==1U && memcmp(old_output,new_output,m.output_size)==0 && memcmp(expected,child_output,100U)==0);
    }
    puts("PASS: DW4 full/partial taps, 3/4/256/257 channels, alignment/stride/zero/negative+positive shift/clamp/bias/abort recovery; complete-acc ReLU finish grid+200k.");
    puts("PASS: per-invocation byte workspace tail, tight/offset arena canaries and different-workspace callback reentry.");
}
static void layer_boundaries(void)
{
    int8_t weights[9*16*5], shifts[16]; int32_t bias[16], multipliers[16];
    const uint16_t channels[]={1,2,3,4,5,7,8,16};
    const int16_t zeros[]={-128,0,127};
    gs_int8_layer_t layer; gs_int8_model_t model; size_t c,z,i; unsigned stride,pad;
    memset(&layer,0,sizeof layer); memset(&model,0,sizeof model);
    for(i=0;i<sizeof weights;++i) { weights[i]=(int8_t)random_word(); }
    for(i=0;i<16;++i) { shifts[i]=(int8_t)(-(int)(i%6)); bias[i]=(int32_t)i*97-701;
        multipliers[i]=INT32_MAX-(int32_t)i*13217; }
    for(i=0;i<sizeof input;++i) { input[i]=(int8_t)random_word(); }
    layer.weights=weights; layer.shifts=shifts; layer.bias=bias; layer.multipliers=multipliers;
    layer.activation_min=-128; layer.activation_max=127; model.layers=&layer;
    model.layer_count=1; model.slot_size=36864;
    for(c=0;c<sizeof channels/sizeof channels[0];++c) {
        for(z=0;z<sizeof zeros/sizeof zeros[0];++z) {
            layer.operation=GS_INT8_CONV; layer.input_h=layer.output_h=2;
            layer.input_w=layer.output_w=3; layer.input_c=channels[c]; layer.output_c=5;
            layer.kernel_h=layer.kernel_w=layer.stride_h=layer.stride_w=1;
            layer.pad_h=layer.pad_w=0; layer.input_zero=zeros[z]; layer.output_zero=zeros[2-z];
            model.input_size=6U*channels[c]; model.output_size=30; compare(&model,input);
            compare(&model,input+1); /* byte-aligned input must use safe scalar loads */
            layer.weights=weights+1; compare(&model,input); layer.weights=weights;
            /* Huge bias must retain generic ordering; zero weights avoid overflow. */
            memset(weights,0,sizeof weights); bias[0]=INT32_MAX; bias[1]=INT32_MIN;
            compare(&model,input); bias[0]=-701; bias[1]=-604;
            for(i=0;i<sizeof weights;++i) { weights[i]=(int8_t)random_word(); }
            layer.operation=GS_INT8_DEPTHWISE; layer.input_h=3; layer.input_w=5;
            layer.output_h=3; layer.output_w=4; layer.output_c=channels[c];
            layer.kernel_h=layer.kernel_w=3;
            for(stride=1;stride<=2;++stride) {
                for(pad=0;pad<=2;++pad) {
                    layer.stride_h=layer.stride_w=(uint16_t)stride;
                    layer.pad_h=layer.pad_w=(uint16_t)pad;
                    model.input_size=15U*channels[c]; model.output_size=12U*channels[c];
                    compare(&model,input);
                }
            }
        }
    }
}
static void vectors(void)
{
    FILE *file=fopen("../../Tests/fixtures/int8_original_50.bin","rb"); unsigned n;
    const gs_int8_model_t *model=gs_static_model_network(); const int frames[]={486,490,494};
    assert(file);
    for(n=0;n<50;++n) { assert(fread(input,1,sizeof input,file)==sizeof input); compare(model,input); }
    assert(fgetc(file)==EOF); fclose(file);
    for(n=0;n<3;++n) {
        char path[100]; snprintf(path,sizeof path,"../../Tests/fixtures/static_model_input_%d.bin",frames[n]);
        file=fopen(path,"rb"); assert(file); assert(fread(input,1,sizeof input,file)==sizeof input);
        assert(fgetc(file)==EOF); fclose(file); compare(model,input);
        {
            size_t layer, previous_size=sizeof input; gs_int8_model_t single=*model;
            memcpy(layer_input,input,sizeof input); single.layer_count=1;
            for(layer=0;layer<model->layer_count;++layer) {
                const gs_int8_layer_t *descriptor=&model->layers[layer];
                single.layers=descriptor; single.input_size=previous_size;
                single.output_size=(size_t)descriptor->output_h*descriptor->output_w*descriptor->output_c;
                compare(&single,layer_input); previous_size=single.output_size;
                memcpy(layer_input,old_output,previous_size);
            }
        }
    }
    callbacks=0;
    assert(gs_round8_execute_progress(model,input,sizeof input,old_output,5,old_workspace,sizeof old_workspace,progress,NULL)==GS_AI_OK);
    assert(callbacks==3623); callbacks=0;
    assert(gs_int8_execute_progress(model,input,sizeof input,new_output,5,new_workspace,sizeof new_workspace,progress,NULL)==GS_AI_OK);
    assert(callbacks==3623 && memcmp(old_output,new_output,5)==0);
    memset(new_output,99,5);
    assert(gs_int8_execute_progress(model,input,sizeof input,new_output,5,new_workspace,sizeof new_workspace,aborting,NULL)==GS_AI_BACKEND_FAILURE);
    for(n=0;n<5;++n) { assert(new_output[n]==99); }
}
static void saved_vector(const char *path)
{
    FILE *file=fopen(path,"rb");assert(file);
    assert(fread(input,1,sizeof input,file)==sizeof input && fgetc(file)==EOF);fclose(file);
    const gs_int8_model_t *model=gs_static_model_network();compare(model,input);
    size_t previous_size=sizeof input;gs_int8_model_t single=*model;
    memcpy(layer_input,input,sizeof input);single.layer_count=1;
    for(size_t layer=0;layer<model->layer_count;++layer) {
        const gs_int8_layer_t *descriptor=&model->layers[layer];
        single.layers=descriptor;single.input_size=previous_size;
        single.output_size=(size_t)descriptor->output_h*descriptor->output_w*descriptor->output_c;
        compare(&single,layer_input);previous_size=single.output_size;
        memcpy(layer_input,old_output,previous_size);
    }
    printf("PASS saved input all29 tensors/scalar+packed logits: %s\n",path);
}
/* Deliberate odd tails/C1 high-side padding and safety fallbacks for new kernels;
 * old raw scalar executor remains the independent numeric oracle. */
static void tiled_boundaries(void)
{
    static int8_t weights[9U*512U], shifts[257];
    static int32_t bias[257], multipliers[257];
    const uint16_t inputs[]={4,8,16,256,260};
    const uint16_t outputs[]={1,2,3,5,8,16,17};
    gs_int8_layer_t l;gs_int8_model_t m;
    memset(&l,0,sizeof l);memset(&m,0,sizeof m);
    for(unsigned i=0;i<sizeof weights;++i) weights[i]=(int8_t)random_word();
    for(unsigned i=0;i<sizeof input;++i) input[i]=(int8_t)random_word();
    for(unsigned i=0;i<257;++i) { bias[i]=(int32_t)i*53-900; multipliers[i]=INT32_MAX-(int32_t)i*743;shifts[i]=(int8_t)(-(int)(i%13)); }
    l.weights=weights;l.bias=bias;l.multipliers=multipliers;l.shifts=shifts;
    l.activation_min=-119;l.activation_max=101;l.input_zero=127;l.output_zero=-128;
    m.layers=&l;m.layer_count=1;m.slot_size=36864;
    l.operation=GS_INT8_CONV;l.input_h=l.output_h=1;l.input_w=l.output_w=3;
    l.kernel_h=l.kernel_w=l.stride_h=l.stride_w=1;
    for(unsigned i=0;i<sizeof inputs/sizeof inputs[0];++i) for(unsigned j=0;j<sizeof outputs/sizeof outputs[0];++j) {
        l.input_c=inputs[i];l.output_c=outputs[j];m.input_size=3U*l.input_c;m.output_size=3U*l.output_c;
        compare(&m,input);compare(&m,input+1); /* Last unpaired pixel/channel. */
    }
    l.input_h=l.input_w=6;l.output_h=l.output_w=3;l.input_c=1;
    l.kernel_h=l.kernel_w=3;l.stride_h=l.stride_w=2;
    for(unsigned j=0;j<sizeof outputs/sizeof outputs[0];++j) for(unsigned pad=0;pad<=2;++pad) {
        l.output_c=outputs[j];l.pad_h=l.pad_w=(int16_t)pad;m.input_size=36;m.output_size=9U*l.output_c;
        compare(&m,input); /* Interior and low/high-side partial taps. */
    }
    memset(weights,0,sizeof weights);bias[0]=INT32_MIN;bias[1]=INT32_MAX;
    l.pad_h=l.pad_w=0;l.output_c=2;m.output_size=18;compare(&m,input); /* Unsafe C1 -> generic. */
    bias[0]=-900;bias[1]=-847;
    for(unsigned i=0;i<sizeof weights;++i) weights[i]=(int8_t)random_word();
    l.operation=GS_INT8_DEPTHWISE;l.input_c=l.output_c=257;
    l.input_h=l.input_w=3;l.output_h=l.output_w=1;l.stride_h=l.stride_w=1;
    m.input_size=9U*257U;m.output_size=257;compare(&m,input); /* Correction cache bound -> old tap path. */
    puts("PASS: C1 partial padding/bias safety, PW 2pixel/2channel odd tails and IC256/260, DW cache bound");
}
static void benchmark(void)
{
    const unsigned runs=100; unsigned n; LARGE_INTEGER start,end,frequency; double old_ms,new_ms;
    const gs_int8_model_t *model=gs_static_model_network();
    assert(QueryPerformanceFrequency(&frequency)); assert(QueryPerformanceCounter(&start));
    for(n=0;n<runs;++n) { assert(gs_round8_execute(model,input,sizeof input,old_output,5,old_workspace,sizeof old_workspace)==GS_AI_OK); }
    assert(QueryPerformanceCounter(&end));
    old_ms=1000.0*(double)(end.QuadPart-start.QuadPart)/(double)frequency.QuadPart/runs;
    assert(QueryPerformanceCounter(&start));
    for(n=0;n<runs;++n) { assert(gs_int8_execute(model,input,sizeof input,new_output,5,new_workspace,sizeof new_workspace)==GS_AI_OK); }
    assert(QueryPerformanceCounter(&end));
    new_ms=1000.0*(double)(end.QuadPart-start.QuadPart)/(double)frequency.QuadPart/runs;
    printf("HOST_ONLY /O2 both: round8 %.3f ms, candidate %.3f ms, relative %.3fx; NOT MCU timing.\n",old_ms,new_ms,old_ms/new_ms);
}
int main(int argc,char **argv)
{
    scale_and_packing(); layer_boundaries(); tiled_boundaries(); depthwise_parallel_boundaries(); vectors();
    for(int n=1;n<argc;++n) saved_vector(argv[n]);
    benchmark();
    puts("PASS: fixed round8 oracle vs candidate scalar/packed, exact original50 + real3 logits and all29 intermediate layers of real3; 200000 requant + signed/tie/shift/saturation/padding/stride/abort boundaries.");
    return 0;
}
