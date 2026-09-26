/**
  ******************************************************************************
  * @file    gs_network.c
  * @author  AST Embedded Analytics Research Platform
  * @date    2026-09-22T17:46:54+0800
  * @brief   AI Tool Automatic Code Generator for Embedded NN computing
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  ******************************************************************************
  */

#include "ai_lite_inspect.h"
#include "ai_platform_interface.h"
#include "layers.h"
#include "core_convert.h"
#include "gs_network.h"
#include <stdbool.h>
extern bool gs_cubeai_layer_done(size_t layer, uint32_t outputs);
#include "gs_network_details.h"
#include "gs_network_data.h"
#include "stai_events.h"

#include "ai_lite_inspect.h"

#include "lite_operators.h"
/*****************************************************************************/
#define STAI_INTERNAL_API_MAJOR               (1)
#define STAI_INTERNAL_API_MINOR               (0)
#define STAI_INTERNAL_API_MICRO               (0)

#define STAI_MAGIC                            (0xB1C00100)

/*****************************************************************************/
#define _STAI_CONCAT_ARG(a, b)     a ## b
#define STAI_CONCAT(a, b)         _STAI_CONCAT_ARG(a, b)

/*!  STAI_CAST SECTION                       *********************************/
#define STAI_CAST(type, expr) \
  ((type)(expr))


/*****************************************************************************/
#define STAI_SIZE(_size) \
  ((stai_size)(_size))

/*****************************************************************************/
#define STAI_INIT_BUFFER(_flags, _size, _address) \
  { \
    .size = (_size), \
    .address = (uintptr_t)(_address), \
    .flags = (_flags), \
  }

#define STAI_INIT_TENSOR(_name, _flags, _fmt, _size_bytes, _shape, _scale, _zeropoint) \
  { \
    .size_bytes = (_size_bytes), \
    .flags = (_flags), \
    .format = (stai_format)(_fmt), \
    .shape = STAI_PACK(_shape), \
    .scale = STAI_PACK(_scale), \
    .zeropoint = STAI_PACK(_zeropoint), \
    .name = (_name) \
  }

#define STAI_INIT_ARRAY(_size, _ptr) \
  { .size = STAI_SIZE(_size), .data = STAI_PACK(_ptr) }


#define STAI_CAST_ARRAY(_type, _size, _ptr) \
  { .size = STAI_SIZE(_size), .data = (_type)STAI_PACK(_ptr) }


#define STAI_DECLARE_ARRAY(_type, _size, ...) \
  { .size = STAI_SIZE(_size), .data = (_type[_size]) { STAI_PACK(__VA_ARGS__) } }


#define STAI_EMPTY_ARRAY() \
  { .size = 0, .data = NULL }


#define STAI_INIT_VERSION(_major, _minor, _micro) \
  { .major = (_major), .minor = (_minor), .micro = (_micro), .reserved = 0x0 }

/*****************************************************************************/
/**  Getters and setters  **/

#define STAI_GET_ARRAY_SIZE(nd_array) \
  (nd_array.size)


#define STAI_GET_ARRAY_ELEM(nd_array, pos) \
  (nd_array.data[(pos)])

#define _STAI_SET_ERROR(net_ctx, cond, value, exit) { \
  if (!(net_ctx)) { return STAI_ERROR_NETWORK_INVALID_CONTEXT_HANDLE; } \
  if (((uintptr_t)net_ctx) & (_STAI_CONTEXT_ALIGNMENT-1)) { return STAI_ERROR_NETWORK_INVALID_CONTEXT_ALIGNMENT; } \
  if (((value) >= STAI_ERROR_GENERIC) && (cond)) { \
    if ((net_ctx)->_return_code == STAI_SUCCESS) { \
      (net_ctx)->_return_code = (value); \
    } \
    return (exit); \
  } \
}

/*****************************************************************************/
/* TODO REMOVE THESE TWO MACROS */
#define STAI_EVENT_NODE_START_CB
#define STAI_EVENT_NODE_STOP_CB

#ifdef STAI_EVENT_NODE_START_CB
#ifndef _STAI_GS_NETWORK_EVENT_NODE_START_CB
  #define _STAI_GS_NETWORK_EVENT_NODE_START_CB(_node_id, _buffers_size, ...) \
  if (net_ctx->_callback) { \
    const stai_event_node_start_stop _start_event = { \
      .node_id=(_node_id), \
      .buffers={ \
        .size=(_buffers_size), \
        .data=(stai_ptr const*)(const stai_ptr[_buffers_size])STAI_PACK(__VA_ARGS__) \
      } \
    }; \
    net_ctx->_callback(net_ctx->_callback_cookie, STAI_EVENT_NODE_START, (const void*)&_start_event); \
  }
#endif
#else
  #define _STAI_GS_NETWORK_EVENT_NODE_START_CB(_node_id, _buffers_size, ...) \
    do { /* _STAI_GS_NETWORK_EVENT_NODE_START_CB() */ } while(0);
#endif      /* STAI_EVENT_NODE_START_CB */

#ifdef STAI_EVENT_NODE_STOP_CB
#ifndef _STAI_GS_NETWORK_EVENT_NODE_STOP_CB
  #define _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(_node_id, _buffers_size, ...) \
  if (net_ctx->_callback) { \
    const stai_event_node_start_stop _stop_event = { \
      .node_id=(_node_id), \
      .buffers={ \
        .size=(_buffers_size), \
        .data=(stai_ptr const*)(stai_ptr[_buffers_size])STAI_PACK(__VA_ARGS__) \
      } \
    }; \
    net_ctx->_callback(net_ctx->_callback_cookie, STAI_EVENT_NODE_STOP, (const void*)&_stop_event); \
  }
#endif
#else
  #define _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(_node_id, _buffers_size, ...) \
    do { /* _STAI_GS_NETWORK_EVENT_NODE_STOP_CB() */ } while(0);
#endif      /* STAI_EVENT_NODE_STOP_CB */


/*****************************************************************************/
#define _STAI_GS_NETWORK_MODEL_SIGNATURE     "0xd296874353b574cf6412d26f8fecd5cb"
#define _STAI_GS_NETWORK_DATETIME            "2026-09-22T17:46:54+0800"
#define _STAI_GS_NETWORK_COMPILE_DATETIME    __DATE__ " " __TIME__

#define _STAI_CONTEXT_ALIGNMENT        STAI_GS_NETWORK_CONTEXT_ALIGNMENT

/*****************************************************************************/
#define g_gs_network_activations_1     (NULL)




#if defined(HAVE_GS_NETWORK_INFO)
/*****************************************************************************/
static const stai_network_info g_gs_network_info = {
  .model_signature = _STAI_GS_NETWORK_MODEL_SIGNATURE,
  .c_compile_datetime = _STAI_GS_NETWORK_COMPILE_DATETIME,
  .c_model_name = STAI_GS_NETWORK_MODEL_NAME,
  .c_model_datetime = _STAI_GS_NETWORK_DATETIME,
  .c_model_signature = 0x0,
  .runtime_version = STAI_INIT_VERSION(12, 0, 1),
  .tool_version = STAI_INIT_VERSION(4, 0, 1),
  .api_version = STAI_INIT_VERSION(1, 0, 0),
  .n_macc = STAI_GS_NETWORK_MACC_NUM,
  .n_nodes = STAI_GS_NETWORK_NODES_NUM,
  .flags = STAI_GS_NETWORK_FLAGS,
  .n_inputs = STAI_GS_NETWORK_IN_NUM,
  .n_outputs = STAI_GS_NETWORK_OUT_NUM,
  .n_activations = STAI_GS_NETWORK_ACTIVATIONS_NUM,
  .n_weights = STAI_GS_NETWORK_WEIGHTS_NUM,
  .n_states = STAI_GS_NETWORK_STATES_NUM,
  .inputs = (stai_tensor[STAI_GS_NETWORK_IN_NUM]) {
    STAI_INIT_TENSOR(
      STAI_GS_NETWORK_IN_1_NAME,
      STAI_GS_NETWORK_IN_1_FLAGS,
      STAI_GS_NETWORK_IN_1_FORMAT,
      STAI_GS_NETWORK_IN_1_SIZE_BYTES,
      STAI_DECLARE_ARRAY(int32_t, 4, 1, 96, 96, 3),
      STAI_DECLARE_ARRAY(float, 1, 1.0f),
      STAI_DECLARE_ARRAY(int16_t, 1, -128)),
    },
    .outputs = (stai_tensor[STAI_GS_NETWORK_OUT_NUM]) {
    STAI_INIT_TENSOR(
      STAI_GS_NETWORK_OUT_1_NAME,
      STAI_GS_NETWORK_OUT_1_FLAGS,
      STAI_GS_NETWORK_OUT_1_FORMAT,
      STAI_GS_NETWORK_OUT_1_SIZE_BYTES,
      STAI_DECLARE_ARRAY(int32_t, 2, 1, 6),
      STAI_DECLARE_ARRAY(float, 1, 0.09457084536552429f),
      STAI_DECLARE_ARRAY(int16_t, 1, -31)),
    },
  .activations = (stai_tensor[STAI_GS_NETWORK_ACTIVATIONS_NUM]) {
    STAI_INIT_TENSOR(
      (NULL),
      STAI_GS_NETWORK_ACTIVATION_1_FLAGS,
      STAI_FORMAT_U8,
      STAI_GS_NETWORK_ACTIVATION_1_SIZE_BYTES,
      STAI_DECLARE_ARRAY(int32_t, 1, 58624),
      STAI_EMPTY_ARRAY(),
      STAI_EMPTY_ARRAY()),
    },
  .weights = (stai_tensor[STAI_GS_NETWORK_WEIGHTS_NUM]) {
    STAI_INIT_TENSOR(
      (NULL),
      STAI_GS_NETWORK_WEIGHT_1_FLAGS,
      STAI_FORMAT_U8,
      STAI_GS_NETWORK_WEIGHT_1_SIZE_BYTES,
      STAI_DECLARE_ARRAY(int32_t, 1, 220112),
      STAI_EMPTY_ARRAY(),
      STAI_EMPTY_ARRAY()),
    },

  .states = NULL
};
#endif

#define _STAI_CONTEXT_ACQUIRE(_net_ctx, _net_handle) \
  _stai_gs_network_context* _net_ctx = (_stai_gs_network_context*)(_net_handle); \
  STAI_ASSERT(_net_ctx != NULL) \
  _STAI_SET_ERROR(_net_ctx, _net_ctx->_magic != STAI_MAGIC, \
                  STAI_ERROR_NETWORK_INVALID_CONTEXT_HANDLE, _net_ctx->_return_code)


/*****************************************************************************/
static
void _stai_gs_network_check(_stai_gs_network_context* net_ctx)
{
  stai_size idx;

// Check activations status
  for (idx=0; idx<STAI_GS_NETWORK_ACTIVATIONS_NUM; idx++) {
    if (net_ctx->_activations[idx] == NULL) break;
  }
  net_ctx->_flags |= (idx == STAI_GS_NETWORK_ACTIVATIONS_NUM) ? STAI_FLAG_ACTIVATIONS : STAI_FLAG_NONE;
// Check inputs status
  for (idx=0; idx<STAI_GS_NETWORK_IN_NUM; idx++) {
    if (net_ctx->_inputs[idx] == NULL) break;
  }
  net_ctx->_flags |= (idx == STAI_GS_NETWORK_IN_NUM) ? STAI_FLAG_INPUTS : STAI_FLAG_NONE;

  // Check outputs status
  for (idx=0; idx<STAI_GS_NETWORK_OUT_NUM; idx++) {
    if (net_ctx->_outputs[idx] == NULL) break;
  }
  net_ctx->_flags |= (idx == STAI_GS_NETWORK_OUT_NUM) ? STAI_FLAG_OUTPUTS : STAI_FLAG_NONE;

// Check weights status
  for (idx=0; idx<STAI_GS_NETWORK_WEIGHTS_NUM; idx++) {
    if (net_ctx->_weights[idx] == NULL) break;
  }
  net_ctx->_flags |= (idx == STAI_GS_NETWORK_WEIGHTS_NUM) ? STAI_FLAG_WEIGHTS : STAI_FLAG_NONE;
STAI_PRINT("  [_stai_network_check] flags: 0x%08x\n", net_ctx->_flags)
}


/*****************************************************************************/
STAI_API_ENTRY
stai_return_code stai_gs_network_init(
  stai_network* network)
{
  /* Memory where to store internal context is provided by applications as a raw byte buffer */
  _stai_gs_network_context* net_ctx = (_stai_gs_network_context*)(network);
  net_ctx->_return_code = STAI_SUCCESS;
  STAI_PRINT("[Entering Network Init] network(%p) context_size(%d)\n", net_ctx, (int32_t)sizeof(_stai_gs_network_context))

  _STAI_SET_ERROR(net_ctx, STAI_GS_NETWORK_CONTEXT_SIZE != sizeof(_stai_gs_network_context),
                 STAI_ERROR_NETWORK_INVALID_CONTEXT_SIZE, net_ctx->_return_code)

  {
    const _stai_gs_network_context _gs_network_context = {
      ._magic = STAI_MAGIC,
      ._signature = STAI_GS_NETWORK_MODEL_SIGNATURE,
      ._flags = STAI_GS_NETWORK_FLAGS,
      ._return_code = STAI_SUCCESS,
      ._callback = NULL,
      ._callback_cookie = NULL,
      ._activations = {
      (stai_ptr)g_gs_network_activations_1
      },
      ._weights = {
      (stai_ptr)g_gs_network_weights_array
      },
      ._inputs = {
    NULL},
      ._outputs = {
    NULL},
    };

    // Deep copy of internal context to opaque buffer provided by app
    *net_ctx = _gs_network_context;

    _stai_gs_network_check(net_ctx);
  }

  return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_deinit(
  stai_network* network)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)

  /*  Reset flags to initial state  */
  net_ctx->_flags = STAI_GS_NETWORK_FLAGS;
  return net_ctx->_return_code;
}

/*****************************************************************************/



/* Int quant #0 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(serving_default_rgb960_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(1.0f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #1 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(eltwise_0_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0117647061124444f),
    AI_PACK_INTQ_ZP(-43)))

/* Int quant #2 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(tfl_pseudo_qconst57_4D_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(3.075740460189991e-05f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #3 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(eltwise_1_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.007843137718737125f),
    AI_PACK_INTQ_ZP(-1)))

/* Int quant #4 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(tfl_pseudo_qconst56_4D_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.003921568859368563f),
    AI_PACK_INTQ_ZP(127)))

/* Int quant #5 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_2_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #6 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_3_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #7 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_4_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #8 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_5_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #9 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_6_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #10 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_7_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #11 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_8_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #12 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_9_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #13 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_10_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #14 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_11_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #15 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_12_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #16 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_13_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #17 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_14_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #18 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_15_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #19 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_16_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #20 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_17_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #21 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_18_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #22 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_19_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #23 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_20_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #24 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_21_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #25 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_22_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #26 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_23_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #27 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_24_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #28 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_25_pad_before_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #29 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(conv2d_28_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))

/* Int quant #30 */
AI_INTQ_INFO_LIST_OBJ_DECLARE(pool_29_output_array_intq, AI_STATIC,
  AI_BUFFER_META_FLAG_SCALE_FLOAT|AI_BUFFER_META_FLAG_ZEROPOINT_S8, 1,
  AI_PACK_INTQ_INFO(
    AI_PACK_INTQ_SCALE(0.0235294122248888f),
    AI_PACK_INTQ_ZP(-128)))



/* Array#0 */
AI_ARRAY_OBJ_DECLARE(
  serving_default_rgb960_output_array, AI_ARRAY_FORMAT_S8|AI_FMT_FLAG_IS_IO,
  NULL, NULL, 27648, AI_STATIC)

/* Array#1 */
AI_ARRAY_OBJ_DECLARE(
  eltwise_0_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 27648, AI_STATIC)

/* Array#2 */
AI_ARRAY_OBJ_DECLARE(
  tfl_pseudo_qconst57_4D_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 1, AI_STATIC)

/* Array#3 */
AI_ARRAY_OBJ_DECLARE(
  eltwise_1_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 27649, AI_STATIC)

/* Array#4 */
AI_ARRAY_OBJ_DECLARE(
  tfl_pseudo_qconst56_4D_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 1, AI_STATIC)

/* Array#5 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_2_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 20000, AI_STATIC)

/* Array#6 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_3_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 20000, AI_STATIC)

/* Array#7 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_4_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 40000, AI_STATIC)

/* Array#8 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_5_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 40000, AI_STATIC)

/* Array#9 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_6_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 21632, AI_STATIC)

/* Array#10 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_7_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 21632, AI_STATIC)

/* Array#11 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_8_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 21632, AI_STATIC)

/* Array#12 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_9_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 21632, AI_STATIC)

/* Array#13 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_10_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 12544, AI_STATIC)

/* Array#14 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_11_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 12544, AI_STATIC)

/* Array#15 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_12_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 12544, AI_STATIC)

/* Array#16 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_13_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 12544, AI_STATIC)

/* Array#17 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_14_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#18 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_15_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#19 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_16_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#20 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_17_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#21 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_18_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#22 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_19_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#23 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_20_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#24 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_21_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#25 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_22_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#26 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_23_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#27 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_24_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#28 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_25_pad_before_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 8192, AI_STATIC)

/* Array#29 */
AI_ARRAY_OBJ_DECLARE(
  conv2d_28_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 2304, AI_STATIC)

/* Array#30 */
AI_ARRAY_OBJ_DECLARE(
  pool_29_output_array, AI_ARRAY_FORMAT_S8,
  NULL, NULL, 256, AI_STATIC)



/* Tensor #0 */
AI_TENSOR_OBJ_DECLARE(
  eltwise_0_output, AI_STATIC,
  121, 0x1,
  AI_SHAPE_INIT(4, 1, 3, 96, 96), AI_STRIDE_INIT(4, 1, 1, 3, 288),
  1, &eltwise_0_output_array, &eltwise_0_output_array_intq)

/* Tensor #1 */
AI_TENSOR_OBJ_DECLARE(
  serving_default_rgb960_output, AI_STATIC,
  128, 0x1,
  AI_SHAPE_INIT(4, 1, 3, 96, 96), AI_STRIDE_INIT(4, 1, 1, 3, 288),
  1, &serving_default_rgb960_output_array, &serving_default_rgb960_output_array_intq)

/* Tensor #2 */
AI_TENSOR_OBJ_DECLARE(
  tfl_pseudo_qconst57_4D, AI_STATIC,
  130, 0x1,
  AI_SHAPE_INIT(4, 1, 1, 1, 1), AI_STRIDE_INIT(4, 1, 1, 1, 1),
  1, &tfl_pseudo_qconst57_4D_array, &tfl_pseudo_qconst57_4D_array_intq)

/* Tensor #3 */
AI_TENSOR_OBJ_DECLARE(
  eltwise_1_output, AI_STATIC,
  122, 0x1,
  AI_SHAPE_INIT(4, 1, 3, 96, 96), AI_STRIDE_INIT(4, 1, 1, 3, 288),
  1, &eltwise_1_output_array, &eltwise_1_output_array_intq)

/* Tensor #4 */
AI_TENSOR_OBJ_DECLARE(
  tfl_pseudo_qconst56_4D, AI_STATIC,
  129, 0x1,
  AI_SHAPE_INIT(4, 1, 1, 1, 1), AI_STRIDE_INIT(4, 1, 1, 1, 1),
  1, &tfl_pseudo_qconst56_4D_array, &tfl_pseudo_qconst56_4D_array_intq)

/* Tensor #5 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_2_output, AI_STATIC,
  86, 0x1,
  AI_SHAPE_INIT(4, 1, 8, 48, 48), AI_STRIDE_INIT(4, 1, 48*48, 1, 48),
  1, &conv2d_2_output_array, &conv2d_2_output_array_intq)

/* Tensor #6 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_3_pad_before_output, AI_STATIC,
  91, 0x1,
  AI_SHAPE_INIT(4, 1, 8, 50, 50), AI_STRIDE_INIT(4, 1, 50*50, 1, 50),
  1, &conv2d_3_pad_before_output_array, &conv2d_3_pad_before_output_array_intq)

/* Tensor #7 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_4_output, AI_STATIC,
  95, 0x1,
  AI_SHAPE_INIT(4, 1, 16, 48, 48), AI_STRIDE_INIT(4, 1, 48*48, 1, 48),
  1, &conv2d_4_output_array, &conv2d_4_output_array_intq)

/* Tensor #8 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_5_pad_before_output, AI_STATIC,
  100, 0x1,
  AI_SHAPE_INIT(4, 1, 16, 50, 50), AI_STRIDE_INIT(4, 1, 50*50, 1, 50),
  1, &conv2d_5_pad_before_output_array, &conv2d_5_pad_before_output_array_intq)

/* Tensor #9 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_6_output, AI_STATIC,
  104, 0x1,
  AI_SHAPE_INIT(4, 1, 32, 24, 24), AI_STRIDE_INIT(4, 1, 24*24, 1, 24),
  1, &conv2d_6_output_array, &conv2d_6_output_array_intq)

/* Tensor #10 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_7_pad_before_output, AI_STATIC,
  109, 0x1,
  AI_SHAPE_INIT(4, 1, 32, 26, 26), AI_STRIDE_INIT(4, 1, 26*26, 1, 26),
  1, &conv2d_7_pad_before_output_array, &conv2d_7_pad_before_output_array_intq)

/* Tensor #11 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_8_output, AI_STATIC,
  113, 0x1,
  AI_SHAPE_INIT(4, 1, 32, 24, 24), AI_STRIDE_INIT(4, 1, 24*24, 1, 24),
  1, &conv2d_8_output_array, &conv2d_8_output_array_intq)

/* Tensor #12 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_9_pad_before_output, AI_STATIC,
  118, 0x1,
  AI_SHAPE_INIT(4, 1, 32, 26, 26), AI_STRIDE_INIT(4, 1, 26*26, 1, 26),
  1, &conv2d_9_pad_before_output_array, &conv2d_9_pad_before_output_array_intq)

/* Tensor #13 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_10_output, AI_STATIC,
  1, 0x1,
  AI_SHAPE_INIT(4, 1, 64, 12, 12), AI_STRIDE_INIT(4, 1, 12*12, 1, 12),
  1, &conv2d_10_output_array, &conv2d_10_output_array_intq)

/* Tensor #14 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_11_pad_before_output, AI_STATIC,
  6, 0x1,
  AI_SHAPE_INIT(4, 1, 64, 14, 14), AI_STRIDE_INIT(4, 1, 14*14, 1, 14),
  1, &conv2d_11_pad_before_output_array, &conv2d_11_pad_before_output_array_intq)

/* Tensor #15 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_12_output, AI_STATIC,
  10, 0x1,
  AI_SHAPE_INIT(4, 1, 64, 12, 12), AI_STRIDE_INIT(4, 1, 12*12, 1, 12),
  1, &conv2d_12_output_array, &conv2d_12_output_array_intq)

/* Tensor #16 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_13_pad_before_output, AI_STATIC,
  15, 0x1,
  AI_SHAPE_INIT(4, 1, 64, 14, 14), AI_STRIDE_INIT(4, 1, 14*14, 1, 14),
  1, &conv2d_13_pad_before_output_array, &conv2d_13_pad_before_output_array_intq)

/* Tensor #17 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_14_output, AI_STATIC,
  19, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 6, 6), AI_STRIDE_INIT(4, 1, 6*6, 1, 6),
  1, &conv2d_14_output_array, &conv2d_14_output_array_intq)

/* Tensor #18 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_15_pad_before_output, AI_STATIC,
  24, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 8, 8), AI_STRIDE_INIT(4, 1, 8*8, 1, 8),
  1, &conv2d_15_pad_before_output_array, &conv2d_15_pad_before_output_array_intq)

/* Tensor #19 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_16_output, AI_STATIC,
  28, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 6, 6), AI_STRIDE_INIT(4, 1, 6*6, 1, 6),
  1, &conv2d_16_output_array, &conv2d_16_output_array_intq)

/* Tensor #20 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_17_pad_before_output, AI_STATIC,
  33, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 8, 8), AI_STRIDE_INIT(4, 1, 8*8, 1, 8),
  1, &conv2d_17_pad_before_output_array, &conv2d_17_pad_before_output_array_intq)

/* Tensor #21 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_18_output, AI_STATIC,
  37, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 6, 6), AI_STRIDE_INIT(4, 1, 6*6, 1, 6),
  1, &conv2d_18_output_array, &conv2d_18_output_array_intq)

/* Tensor #22 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_19_pad_before_output, AI_STATIC,
  42, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 8, 8), AI_STRIDE_INIT(4, 1, 8*8, 1, 8),
  1, &conv2d_19_pad_before_output_array, &conv2d_19_pad_before_output_array_intq)

/* Tensor #23 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_20_output, AI_STATIC,
  46, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 6, 6), AI_STRIDE_INIT(4, 1, 6*6, 1, 6),
  1, &conv2d_20_output_array, &conv2d_20_output_array_intq)

/* Tensor #24 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_21_pad_before_output, AI_STATIC,
  51, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 8, 8), AI_STRIDE_INIT(4, 1, 8*8, 1, 8),
  1, &conv2d_21_pad_before_output_array, &conv2d_21_pad_before_output_array_intq)

/* Tensor #25 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_22_output, AI_STATIC,
  55, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 6, 6), AI_STRIDE_INIT(4, 1, 6*6, 1, 6),
  1, &conv2d_22_output_array, &conv2d_22_output_array_intq)

/* Tensor #26 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_23_pad_before_output, AI_STATIC,
  60, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 8, 8), AI_STRIDE_INIT(4, 1, 8*8, 1, 8),
  1, &conv2d_23_pad_before_output_array, &conv2d_23_pad_before_output_array_intq)

/* Tensor #27 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_24_output, AI_STATIC,
  64, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 6, 6), AI_STRIDE_INIT(4, 1, 6*6, 1, 6),
  1, &conv2d_24_output_array, &conv2d_24_output_array_intq)

/* Tensor #28 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_25_pad_before_output, AI_STATIC,
  69, 0x1,
  AI_SHAPE_INIT(4, 1, 128, 8, 8), AI_STRIDE_INIT(4, 1, 8*8, 1, 8),
  1, &conv2d_25_pad_before_output_array, &conv2d_25_pad_before_output_array_intq)

/* Tensor #29 */
AI_TENSOR_OBJ_DECLARE(
  conv2d_28_output, AI_STATIC,
  82, 0x1,
  AI_SHAPE_INIT(4, 1, 256, 3, 3), AI_STRIDE_INIT(4, 1, 1, 256, 768),
  1, &conv2d_28_output_array, &conv2d_28_output_array_intq)

/* Tensor #30 */
AI_TENSOR_OBJ_DECLARE(
  pool_29_output, AI_STATIC,
  127, 0x1,
  AI_SHAPE_INIT(4, 1, 256, 1, 1), AI_STRIDE_INIT(4, 1, 1, 256, 256),
  1, &pool_29_output_array, &pool_29_output_array_intq)


AI_TENSOR_CHAIN_OBJ_DECLARE(
  eltwise_0_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 2, &serving_default_rgb960_output, &tfl_pseudo_qconst57_4D),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &eltwise_0_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  eltwise_0_layer, 0,
  ELTWISE_INTEGER_TYPE, 0x0, NULL,
  eltwise_integer, forward_eltwise_integer_INT8,
  &eltwise_0_chain,
  NULL, &eltwise_0_layer, AI_STATIC, 
  .operation = ai_mul_f32, 
  .buffer_operation = ai_mul_buffer_INT8, 
)

AI_TENSOR_CHAIN_OBJ_DECLARE(
  eltwise_1_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 2, &eltwise_0_output, &tfl_pseudo_qconst56_4D),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &eltwise_1_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  eltwise_1_layer, 1,
  ELTWISE_INTEGER_TYPE, 0x0, NULL,
  eltwise_integer, forward_eltwise_integer_INT8,
  &eltwise_1_chain,
  NULL, &eltwise_1_layer, AI_STATIC, 
  .operation = ai_sum_f32, 
  .buffer_operation = ai_sum_buffer_INT8, 
)


AI_STATIC_CONST ai_i8 conv2d_3_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_3_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_3_pad_before_value_data, conv2d_3_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_3_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_2_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_3_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_3_pad_before_layer, 3,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_3_pad_before_chain,
  NULL, &conv2d_3_pad_before_layer, AI_STATIC, 
  .value = &conv2d_3_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 1, 1, 1, 1), 
)


AI_STATIC_CONST ai_i8 conv2d_5_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_5_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_5_pad_before_value_data, conv2d_5_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_5_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_4_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_5_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_5_pad_before_layer, 5,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_5_pad_before_chain,
  NULL, &conv2d_5_pad_before_layer, AI_STATIC, 
  .value = &conv2d_5_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 0, 0, 2, 2), 
)


AI_STATIC_CONST ai_i8 conv2d_7_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_7_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_7_pad_before_value_data, conv2d_7_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_7_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_6_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_7_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_7_pad_before_layer, 7,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_7_pad_before_chain,
  NULL, &conv2d_7_pad_before_layer, AI_STATIC, 
  .value = &conv2d_7_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 1, 1, 1, 1), 
)


AI_STATIC_CONST ai_i8 conv2d_9_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_9_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_9_pad_before_value_data, conv2d_9_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_9_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_8_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_9_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_9_pad_before_layer, 9,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_9_pad_before_chain,
  NULL, &conv2d_9_pad_before_layer, AI_STATIC, 
  .value = &conv2d_9_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 0, 0, 2, 2), 
)


AI_STATIC_CONST ai_i8 conv2d_11_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_11_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_11_pad_before_value_data, conv2d_11_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_11_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_10_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_11_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_11_pad_before_layer, 11,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_11_pad_before_chain,
  NULL, &conv2d_11_pad_before_layer, AI_STATIC, 
  .value = &conv2d_11_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 1, 1, 1, 1), 
)


AI_STATIC_CONST ai_i8 conv2d_13_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_13_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_13_pad_before_value_data, conv2d_13_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_13_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_12_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_13_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_13_pad_before_layer, 13,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_13_pad_before_chain,
  NULL, &conv2d_13_pad_before_layer, AI_STATIC, 
  .value = &conv2d_13_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 0, 0, 2, 2), 
)


AI_STATIC_CONST ai_i8 conv2d_15_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_15_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_15_pad_before_value_data, conv2d_15_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_15_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_14_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_15_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_15_pad_before_layer, 15,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_15_pad_before_chain,
  NULL, &conv2d_15_pad_before_layer, AI_STATIC, 
  .value = &conv2d_15_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 1, 1, 1, 1), 
)


AI_STATIC_CONST ai_i8 conv2d_17_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_17_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_17_pad_before_value_data, conv2d_17_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_17_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_16_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_17_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_17_pad_before_layer, 17,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_17_pad_before_chain,
  NULL, &conv2d_17_pad_before_layer, AI_STATIC, 
  .value = &conv2d_17_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 1, 1, 1, 1), 
)


AI_STATIC_CONST ai_i8 conv2d_19_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_19_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_19_pad_before_value_data, conv2d_19_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_19_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_18_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_19_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_19_pad_before_layer, 19,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_19_pad_before_chain,
  NULL, &conv2d_19_pad_before_layer, AI_STATIC, 
  .value = &conv2d_19_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 1, 1, 1, 1), 
)


AI_STATIC_CONST ai_i8 conv2d_21_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_21_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_21_pad_before_value_data, conv2d_21_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_21_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_20_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_21_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_21_pad_before_layer, 21,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_21_pad_before_chain,
  NULL, &conv2d_21_pad_before_layer, AI_STATIC, 
  .value = &conv2d_21_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 1, 1, 1, 1), 
)


AI_STATIC_CONST ai_i8 conv2d_23_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_23_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_23_pad_before_value_data, conv2d_23_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_23_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_22_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_23_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_23_pad_before_layer, 23,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_23_pad_before_chain,
  NULL, &conv2d_23_pad_before_layer, AI_STATIC, 
  .value = &conv2d_23_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 1, 1, 1, 1), 
)


AI_STATIC_CONST ai_i8 conv2d_25_pad_before_value_data[] = { -128 };
AI_ARRAY_OBJ_DECLARE(
    conv2d_25_pad_before_value, AI_ARRAY_FORMAT_S8,
    conv2d_25_pad_before_value_data, conv2d_25_pad_before_value_data, 1, AI_STATIC_CONST)
AI_TENSOR_CHAIN_OBJ_DECLARE(
  conv2d_25_pad_before_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_24_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_25_pad_before_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  conv2d_25_pad_before_layer, 25,
  PAD_TYPE, 0x0, NULL,
  pad, forward_pad,
  &conv2d_25_pad_before_chain,
  NULL, &conv2d_25_pad_before_layer, AI_STATIC, 
  .value = &conv2d_25_pad_before_value, 
  .mode = AI_PAD_8BIT_CH1ST_CONSTANT, 
  .pads = AI_SHAPE_INIT(4, 0, 0, 2, 2), 
)

AI_TENSOR_CHAIN_OBJ_DECLARE(
  pool_29_chain, AI_STATIC_CONST, 4,
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &conv2d_28_output),
  AI_TENSOR_LIST_OBJ_INIT(AI_FLAG_NONE, 1, &pool_29_output),
  AI_TENSOR_LIST_OBJ_EMPTY,
  AI_TENSOR_LIST_OBJ_EMPTY
)

AI_LAYER_OBJ_DECLARE(
  pool_29_layer, 29,
  POOL_TYPE, 0x0, NULL,
  pool, forward_ap_integer_INT8,
  &pool_29_chain,
  NULL, &pool_29_layer, AI_STATIC, 
  .pool_size = AI_SHAPE_2D_INIT(3, 3), 
  .pool_stride = AI_SHAPE_2D_INIT(3, 3), 
  .pool_pad = AI_SHAPE_INIT(4, 0, 0, 0, 0), 
)
/**  Hybrid layers declarations section  *************************************/
void forward_lite_eltwise_integer_INT8_eltwise_0(_stai_gs_network_context* net_ctx)
{
  serving_default_rgb960_output_array.data = AI_PTR(net_ctx->_inputs[0] + 0);
  serving_default_rgb960_output_array.data_start = AI_PTR(net_ctx->_inputs[0] + 0);
  tfl_pseudo_qconst57_4D_array.data = AI_PTR(net_ctx->_weights[0] + 0);
  tfl_pseudo_qconst57_4D_array.data_start = AI_PTR(net_ctx->_weights[0] + 0);
  eltwise_0_output_array.data = AI_PTR(net_ctx->_activations[0] + 27844);
  eltwise_0_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 27844);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(0, 2, { serving_default_rgb960_output.data->data,tfl_pseudo_qconst57_4D.data->data});
  forward_eltwise_integer_INT8(&eltwise_0_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(0, 1, { eltwise_0_output.data->data});
}
void forward_lite_eltwise_integer_INT8_eltwise_1(_stai_gs_network_context* net_ctx)
{
  eltwise_0_output_array.data = AI_PTR(net_ctx->_activations[0] + 27844);
  eltwise_0_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 27844);
  tfl_pseudo_qconst56_4D_array.data = AI_PTR(net_ctx->_weights[0] + 4);
  tfl_pseudo_qconst56_4D_array.data_start = AI_PTR(net_ctx->_weights[0] + 4);
  eltwise_1_output_array.data = AI_PTR(net_ctx->_activations[0] + 192);
  eltwise_1_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 192);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(1, 2, { eltwise_0_output.data->data,tfl_pseudo_qconst56_4D.data->data});
  forward_eltwise_integer_INT8(&eltwise_1_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(1, 1, { eltwise_1_output.data->data});
}
void forward_lite_pad_conv2d_3_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_2_output_array.data = AI_PTR(net_ctx->_activations[0] + 27844);
  conv2d_2_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 27844);
  conv2d_3_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 27844);
  conv2d_3_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 27844);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(3, 1, { conv2d_2_output.data->data});
  forward_pad(&conv2d_3_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(3, 1, { conv2d_3_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_5_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_4_output_array.data = AI_PTR(net_ctx->_activations[0] + 18624);
  conv2d_4_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 18624);
  conv2d_5_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 18624);
  conv2d_5_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 18624);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(5, 1, { conv2d_4_output.data->data});
  forward_pad(&conv2d_5_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(5, 1, { conv2d_5_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_7_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_6_output_array.data = AI_PTR(net_ctx->_activations[0] + 9760);
  conv2d_6_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 9760);
  conv2d_7_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 9760);
  conv2d_7_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 9760);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(7, 1, { conv2d_6_output.data->data});
  forward_pad(&conv2d_7_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(7, 1, { conv2d_7_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_9_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_8_output_array.data = AI_PTR(net_ctx->_activations[0] + 448);
  conv2d_8_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 448);
  conv2d_9_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 448);
  conv2d_9_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 448);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(9, 1, { conv2d_8_output.data->data});
  forward_pad(&conv2d_9_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(9, 1, { conv2d_9_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_11_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_10_output_array.data = AI_PTR(net_ctx->_activations[0] + 768);
  conv2d_10_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 768);
  conv2d_11_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 768);
  conv2d_11_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 768);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(11, 1, { conv2d_10_output.data->data});
  forward_pad(&conv2d_11_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(11, 1, { conv2d_11_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_13_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_12_output_array.data = AI_PTR(net_ctx->_activations[0] + 896);
  conv2d_12_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 896);
  conv2d_13_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 896);
  conv2d_13_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 896);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(13, 1, { conv2d_12_output.data->data});
  forward_pad(&conv2d_13_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(13, 1, { conv2d_13_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_15_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_14_output_array.data = AI_PTR(net_ctx->_activations[0] + 1536);
  conv2d_14_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1536);
  conv2d_15_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 1536);
  conv2d_15_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1536);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(15, 1, { conv2d_14_output.data->data});
  forward_pad(&conv2d_15_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(15, 1, { conv2d_15_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_17_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_16_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_16_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_17_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_17_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(17, 1, { conv2d_16_output.data->data});
  forward_pad(&conv2d_17_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(17, 1, { conv2d_17_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_19_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_18_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_18_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_19_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_19_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(19, 1, { conv2d_18_output.data->data});
  forward_pad(&conv2d_19_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(19, 1, { conv2d_19_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_21_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_20_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_20_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_21_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_21_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(21, 1, { conv2d_20_output.data->data});
  forward_pad(&conv2d_21_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(21, 1, { conv2d_21_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_23_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_22_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_22_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_23_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_23_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(23, 1, { conv2d_22_output.data->data});
  forward_pad(&conv2d_23_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(23, 1, { conv2d_23_pad_before_output.data->data});
}
void forward_lite_pad_conv2d_25_pad_before(_stai_gs_network_context* net_ctx)
{
  conv2d_24_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_24_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_25_pad_before_output_array.data = AI_PTR(net_ctx->_activations[0] + 1792);
  conv2d_25_pad_before_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 1792);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(25, 1, { conv2d_24_output.data->data});
  forward_pad(&conv2d_25_pad_before_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(25, 1, { conv2d_25_pad_before_output.data->data});
}
void forward_lite_ap_integer_INT8_pool_29(_stai_gs_network_context* net_ctx)
{
  conv2d_28_output_array.data = AI_PTR(net_ctx->_activations[0] + 5888);
  conv2d_28_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 5888);
  pool_29_output_array.data = AI_PTR(net_ctx->_activations[0] + 0);
  pool_29_output_array.data_start = AI_PTR(net_ctx->_activations[0] + 0);
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(29, 1, { conv2d_28_output.data->data});
  forward_ap_integer_INT8(&pool_29_layer);
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(29, 1, { pool_29_output.data->data});
}

/*****************************************************************************/




static const ai_u16 conv2d_2_t_in_0_shape_w_const_u16 = 96;
static const ai_u16 conv2d_2_t_out_0_shape_ch_const_u16 = 8;
static const ai_u16 conv2d_2_t_weight_0_shape_w_const_u16 = 3;
static const ai_i32 conv2d_2_l_pad_W_0_const_s32 = 0;
static const ai_u16 conv2d_2_l_stride_0_const_u16 = 2;
static const ai_i8 conv2d_2_t_in_0_fmt_zero_const_s8 = -1;
static const ai_i8 conv2d_2_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_2_t_in_0_fmt_scale_const_f32 = 0.007843137718737125f;
static const ai_float conv2d_2_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_2_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.018807213753461838f, 0.0014676899882033467f, 0.003028500359505415f, 1.4895927336056047e-07f, 0.005714842583984137f, 0.0036427518352866173f, 0.010102150030434132f, 1.0786689763619961e-08f);
static const ai_layer_format_type conv2d_2_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME;
static const ai_u16 conv2d_2_t_out_0_shape_w_const_u16 = 48;


static const ai_u16 conv2d_3_t_in_0_shape_w_const_u16 = 50;
static const ai_u16 conv2d_3_t_in_0_shape_h_const_u16 = 50;
static const ai_u16 conv2d_3_t_in_0_shape_ch_const_u16 = 8;
static const ai_u16 conv2d_3_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_3_l_stride_0_const_u16 = 1;
static const ai_i8 conv2d_3_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_3_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_3_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_3_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_3_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.016219088807702065f, 0.012729525566101074f, 0.006878570653498173f, 0.5573070049285889f, 0.0071037872694432735f, 0.01132049411535263f, 0.014341674745082855f, 0.04770585522055626f);
static const ai_u16 conv2d_3_t_out_0_shape_w_const_u16 = 48;
static const ai_u16 conv2d_3_t_out_0_shape_h_const_u16 = 48;

static const ai_u16 conv2d_4_t_in_0_shape_w_const_u16 = 48;
static const ai_u16 conv2d_4_t_in_0_shape_h_const_u16 = 48;
static const ai_u16 conv2d_4_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_4_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_4_t_in_0_shape_ch_const_u16 = 8;
static const ai_u16 conv2d_4_t_out_0_shape_ch_const_u16 = 16;
static const ai_i8 conv2d_4_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_4_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_4_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_4_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_4_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.0055263652466237545f, 1.4241002155301885e-08f, 0.006941060069948435f, 6.39666808410766e-08f, 7.330169182750979e-08f, 0.007800919469445944f, 0.0030956226401031017f, 0.003989150747656822f, 3.9694473485951676e-08f, 0.008460032753646374f, 2.28384386957714e-08f, 1.0044245435381072e-08f, 0.00484610116109252f, 0.006930577103048563f, 6.932487650601615e-08f, 6.46138076376701e-08f);
static const ai_layer_format_type conv2d_4_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME2;


static const ai_u16 conv2d_5_t_in_0_shape_w_const_u16 = 50;
static const ai_u16 conv2d_5_t_in_0_shape_h_const_u16 = 50;
static const ai_u16 conv2d_5_t_in_0_shape_ch_const_u16 = 16;
static const ai_u16 conv2d_5_l_stride_1_const_u16 = 2;
static const ai_u16 conv2d_5_l_stride_0_const_u16 = 2;
static const ai_i8 conv2d_5_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_5_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_5_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_5_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_5_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.007331328000873327f, 0.10311706364154816f, 0.008081119507551193f, 0.19242076575756073f, 0.3812832236289978f, 0.00685147987678647f, 0.0341043584048748f, 0.010269995778799057f, 0.13068662583827972f, 0.008189660497009754f, 0.009563369676470757f, 0.006582767236977816f, 0.013152922503650188f, 0.006385603919625282f, 0.11802739650011063f, 0.23880471289157867f);
static const ai_u16 conv2d_5_t_out_0_shape_w_const_u16 = 24;
static const ai_u16 conv2d_5_t_out_0_shape_h_const_u16 = 24;

static const ai_u16 conv2d_6_t_in_0_shape_w_const_u16 = 24;
static const ai_u16 conv2d_6_t_in_0_shape_h_const_u16 = 24;
static const ai_u16 conv2d_6_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_6_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_6_t_in_0_shape_ch_const_u16 = 16;
static const ai_u16 conv2d_6_t_out_0_shape_ch_const_u16 = 32;
static const ai_i8 conv2d_6_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_6_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_6_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_6_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_6_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.010584037750959396f, 0.15221622586250305f, 0.008570891804993153f, 0.022050101310014725f, 0.0120157515630126f, 0.011779194697737694f, 0.022224394604563713f, 2.995957260054638e-08f, 0.0008772591245360672f, 0.008982375264167786f, 3.937008052901092e-09f, 0.006420182529836893f, 0.007763864006847143f, 0.008486178703606129f, 0.007655666209757328f, 0.006618949119001627f, 0.0085624810308218f, 0.004665580112487078f, 0.007453381549566984f, 0.0620807409286499f, 0.012223911471664906f, 0.016029851511120796f, 0.013402588665485382f, 0.05687765032052994f, 0.006972442846745253f, 0.03529764711856842f, 0.013296612538397312f, 0.0051166159100830555f, 0.010891016572713852f, 0.007633676286786795f, 0.015739254653453827f, 0.00980397593230009f);
static const ai_layer_format_type conv2d_6_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME;


static const ai_u16 conv2d_7_t_in_0_shape_w_const_u16 = 26;
static const ai_u16 conv2d_7_t_in_0_shape_h_const_u16 = 26;
static const ai_u16 conv2d_7_t_in_0_shape_ch_const_u16 = 32;
static const ai_u16 conv2d_7_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_7_l_stride_0_const_u16 = 1;
static const ai_i8 conv2d_7_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_7_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_7_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_7_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_7_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.025721115991473198f, 0.004026554059237242f, 0.011863429099321365f, 0.006061188876628876f, 0.007158227264881134f, 0.0248795785009861f, 0.0051576015539467335f, 0.001543650752864778f, 0.004395336378365755f, 0.05651351809501648f, 0.003725477959960699f, 0.08012843132019043f, 0.0905798077583313f, 0.014687368646264076f, 0.012131428346037865f, 0.012065918184816837f, 0.07437139004468918f, 0.023570341989398003f, 0.011608113534748554f, 0.004945756401866674f, 0.016413386911153793f, 0.011980884708464146f, 0.010509473271667957f, 0.006481681484729052f, 0.01770487241446972f, 0.005095387808978558f, 0.007807886693626642f, 0.12428073585033417f, 0.005257965996861458f, 0.010723820887506008f, 0.005549408029764891f, 0.009818092919886112f);
static const ai_u16 conv2d_7_t_out_0_shape_w_const_u16 = 24;
static const ai_u16 conv2d_7_t_out_0_shape_h_const_u16 = 24;

static const ai_u16 conv2d_8_t_in_0_shape_w_const_u16 = 24;
static const ai_u16 conv2d_8_t_in_0_shape_h_const_u16 = 24;
static const ai_u16 conv2d_8_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_8_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_8_t_in_0_shape_ch_const_u16 = 32;
static const ai_u16 conv2d_8_t_out_0_shape_ch_const_u16 = 32;
static const ai_i8 conv2d_8_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_8_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_8_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_8_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_8_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.003395605832338333f, 0.0030936638358980417f, 0.005386892706155777f, 0.00928041897714138f, 0.001993795158341527f, 0.00403866870328784f, 0.0018095242558047175f, 0.0037693376652896404f, 0.005350587423890829f, 0.002939895261079073f, 0.00735912611708045f, 0.00756827462464571f, 0.003802106250077486f, 0.006837604567408562f, 0.008986737579107285f, 0.004050340969115496f, 0.0061567104421556f, 0.003952729981392622f, 0.007431815378367901f, 3.937008052901092e-09f, 0.003628095844760537f, 0.011624030768871307f, 0.004457331728190184f, 0.0073804715648293495f, 0.004741104785352945f, 0.0030441044364124537f, 0.008736710995435715f, 0.0051343501545488834f, 0.0018812260823324323f, 0.002531326375901699f, 0.008915320038795471f, 0.002329883398488164f);
static const ai_layer_format_type conv2d_8_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME2;


static const ai_u16 conv2d_9_t_in_0_shape_w_const_u16 = 26;
static const ai_u16 conv2d_9_t_in_0_shape_h_const_u16 = 26;
static const ai_u16 conv2d_9_t_in_0_shape_ch_const_u16 = 32;
static const ai_u16 conv2d_9_l_stride_1_const_u16 = 2;
static const ai_u16 conv2d_9_l_stride_0_const_u16 = 2;
static const ai_i8 conv2d_9_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_9_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_9_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_9_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_9_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.004756912589073181f, 0.003228327026590705f, 0.0052771964110434055f, 0.0019331458024680614f, 0.009250139817595482f, 0.004311263095587492f, 0.006409027613699436f, 0.0031630517914891243f, 0.0043370043858885765f, 0.003332514548674226f, 0.0034413922112435102f, 0.002316828351467848f, 0.005216653924435377f, 0.0036513095255941153f, 0.0025739879347383976f, 0.003468603128567338f, 0.004308145958930254f, 0.006082973442971706f, 0.004530978389084339f, 0.004784959368407726f, 0.005098049528896809f, 0.0027525490149855614f, 0.0051963902078568935f, 0.003144143847748637f, 0.0024177883751690388f, 0.00699180644005537f, 0.004252802114933729f, 0.003206950146704912f, 0.009877579286694527f, 0.007470589596778154f, 0.0029961939435452223f, 0.003755799727514386f);
static const ai_u16 conv2d_9_t_out_0_shape_w_const_u16 = 12;
static const ai_u16 conv2d_9_t_out_0_shape_h_const_u16 = 12;

static const ai_u16 conv2d_10_t_in_0_shape_w_const_u16 = 12;
static const ai_u16 conv2d_10_t_in_0_shape_h_const_u16 = 12;
static const ai_u16 conv2d_10_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_10_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_10_t_in_0_shape_ch_const_u16 = 32;
static const ai_u16 conv2d_10_t_out_0_shape_ch_const_u16 = 64;
static const ai_i8 conv2d_10_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_10_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_10_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_10_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_10_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.005528562236577272f, 0.005677404347807169f, 0.016684258356690407f, 0.006594385020434856f, 0.004180542659014463f, 0.017417581751942635f, 0.006748933345079422f, 0.003958430606871843f, 0.0070518990978598595f, 0.012839507311582565f, 0.005172336008399725f, 0.007324769627302885f, 0.010399477556347847f, 0.009584951214492321f, 0.011304840445518494f, 0.008107445202767849f, 0.006666698958724737f, 0.0034186625853180885f, 0.0075740329921245575f, 0.012972461059689522f, 0.012341039255261421f, 0.004969206638634205f, 0.004693183582276106f, 0.0030853324569761753f, 0.005840761121362448f, 0.004695679061114788f, 0.008110149763524532f, 0.01308916974812746f, 0.005846611689776182f, 0.008686646819114685f, 0.0035295390989631414f, 0.004000284243375063f, 0.00543212890625f, 0.00391181418672204f, 0.0049336799420416355f, 0.011300581507384777f, 0.007122345734387636f, 0.0050428700633347034f, 0.0022437714505940676f, 0.00595575338229537f, 0.0079906415194273f, 0.006615740712732077f, 0.0051841139793396f, 0.008927862159907818f, 0.011303195729851723f, 0.007678655441850424f, 0.006685450207442045f, 0.008917759172618389f, 0.008204958401620388f, 0.00903385691344738f, 0.005343858152627945f, 0.0021440419368445873f, 0.006310382857918739f, 0.007499914616346359f, 0.029272932559251785f, 0.004770844709128141f, 0.008546089753508568f, 0.006359066814184189f, 0.004788017366081476f, 0.006434179842472076f, 0.004973516333848238f, 0.006968559231609106f, 0.00659018661826849f, 0.0061370134353637695f);
static const ai_layer_format_type conv2d_10_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME;


static const ai_u16 conv2d_11_t_in_0_shape_w_const_u16 = 14;
static const ai_u16 conv2d_11_t_in_0_shape_h_const_u16 = 14;
static const ai_u16 conv2d_11_t_in_0_shape_ch_const_u16 = 64;
static const ai_u16 conv2d_11_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_11_l_stride_0_const_u16 = 1;
static const ai_i8 conv2d_11_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_11_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_11_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_11_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_11_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.0070413933135569096f, 0.008283538743853569f, 0.0036409494932740927f, 0.008837899193167686f, 0.014746728353202343f, 0.0027435296215116978f, 0.00832313857972622f, 0.011161832138895988f, 0.013103130273520947f, 0.005372286774218082f, 0.00966986920684576f, 0.013106408528983593f, 0.002298221690580249f, 0.006923706270754337f, 0.009374340064823627f, 0.006870792247354984f, 0.009370340034365654f, 0.023494193330407143f, 0.008624915033578873f, 0.0049142250791192055f, 0.003186414483934641f, 0.011255290359258652f, 0.013335853815078735f, 0.019126780331134796f, 0.015943124890327454f, 0.01083587110042572f, 0.00410877401009202f, 0.004150669556111097f, 0.01031479611992836f, 0.0042657251469790936f, 0.01984456367790699f, 0.009116495959460735f, 0.00968205276876688f, 0.019651519134640694f, 0.01845010183751583f, 0.0037635646294802427f, 0.0052573708817362785f, 0.006794804707169533f, 0.016187412664294243f, 0.008413615636527538f, 0.006064349319785833f, 0.007065744139254093f, 0.011551565490663052f, 0.006585188675671816f, 0.005157156381756067f, 0.011660668067634106f, 0.014759785495698452f, 0.009903067722916603f, 0.007959726266562939f, 0.0046597374603152275f, 0.004801691044121981f, 0.014265893958508968f, 0.005976994521915913f, 0.005392300896346569f, 0.005992409773170948f, 0.00853639654815197f, 0.0071246204897761345f, 0.004128140397369862f, 0.010850079357624054f, 0.013686899095773697f, 0.01892532780766487f, 0.013583349995315075f, 0.006421167869120836f, 0.010090090334415436f);
static const ai_u16 conv2d_11_t_out_0_shape_w_const_u16 = 12;
static const ai_u16 conv2d_11_t_out_0_shape_h_const_u16 = 12;

static const ai_u16 conv2d_12_t_in_0_shape_w_const_u16 = 12;
static const ai_u16 conv2d_12_t_in_0_shape_h_const_u16 = 12;
static const ai_u16 conv2d_12_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_12_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_12_t_in_0_shape_ch_const_u16 = 64;
static const ai_u16 conv2d_12_t_out_0_shape_ch_const_u16 = 64;
static const ai_i8 conv2d_12_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_12_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_12_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_12_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_12_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.012289113365113735f, 0.008534620516002178f, 0.00538640096783638f, 0.005392863415181637f, 0.002401703968644142f, 0.012815233319997787f, 0.002715988317504525f, 0.009791259653866291f, 0.013684744015336037f, 0.0029567198362201452f, 0.0031725482549518347f, 0.006583507172763348f, 0.004201333504170179f, 0.011772268451750278f, 0.003839261829853058f, 0.0070915790274739265f, 0.008278789930045605f, 0.001699378015473485f, 0.012596134096384048f, 0.006075965706259012f, 0.009267528541386127f, 0.0035305595956742764f, 0.012890626676380634f, 0.011196118779480457f, 0.009949695318937302f, 0.007792171090841293f, 0.002616273472085595f, 0.00548860989511013f, 0.0038016631733626127f, 0.0036512198857963085f, 0.006014122162014246f, 0.008799191564321518f, 0.008890443481504917f, 0.010159769095480442f, 0.004346300382167101f, 0.005421160254627466f, 0.005479827057570219f, 0.0047838687896728516f, 0.00263492320664227f, 0.030479060485959053f, 0.005625012330710888f, 0.009478684514760971f, 0.007678020279854536f, 0.007819214835762978f, 0.008762040175497532f, 0.013406279496848583f, 0.010931185446679592f, 0.004498266149312258f, 0.0058136447332799435f, 0.006947565358132124f, 0.008581285364925861f, 0.008528049103915691f, 0.01690496690571308f, 0.0016629199963063002f, 0.021769648417830467f, 0.004824552219361067f, 0.006215032190084457f, 0.005539909470826387f, 0.006292447913438082f, 0.0045289634726941586f, 0.0039247917011380196f, 0.017930148169398308f, 0.009263054467737675f, 0.003631304483860731f);
static const ai_layer_format_type conv2d_12_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME2;


static const ai_u16 conv2d_13_t_in_0_shape_w_const_u16 = 14;
static const ai_u16 conv2d_13_t_in_0_shape_h_const_u16 = 14;
static const ai_u16 conv2d_13_t_in_0_shape_ch_const_u16 = 64;
static const ai_u16 conv2d_13_l_stride_1_const_u16 = 2;
static const ai_u16 conv2d_13_l_stride_0_const_u16 = 2;
static const ai_i8 conv2d_13_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_13_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_13_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_13_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_13_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.004253628198057413f, 0.002874715020880103f, 0.002046681009232998f, 0.003325402271002531f, 0.004256955347955227f, 0.0018083835020661354f, 0.0036587559152394533f, 0.002822991693392396f, 0.0017529923934489489f, 0.005243146792054176f, 0.00599399721249938f, 0.0039061615243554115f, 0.0026701027527451515f, 0.0013706196332350373f, 0.002378526609390974f, 0.0021560543682426214f, 0.002098691649734974f, 0.010355417616665363f, 0.003698537824675441f, 0.003078013425692916f, 0.002111705020070076f, 0.0024327936116605997f, 0.002172280102968216f, 0.0020894622430205345f, 0.002142365323379636f, 0.0036645210348069668f, 0.003770852228626609f, 0.0026404508389532566f, 0.002747354796156287f, 0.0038786253426223993f, 0.006760553922504187f, 0.0017371298745274544f, 0.00433258805423975f, 0.003609469858929515f, 0.005465252790600061f, 0.0028268105816096067f, 0.0027804861310869455f, 0.004967779852449894f, 0.003062395378947258f, 0.0015844228910282254f, 0.002542097121477127f, 0.0025264956057071686f, 0.006715687457472086f, 0.0035021852236241102f, 0.0017385229002684355f, 0.0016403383342549205f, 0.004535390995442867f, 0.0067910607904195786f, 0.003509990870952606f, 0.0037905448116362095f, 0.0018796933582052588f, 0.003300118027254939f, 0.0019412419060245156f, 0.007205473259091377f, 0.0013323299353942275f, 0.0041446019895374775f, 0.003365534357726574f, 0.004069107118993998f, 0.003806097200140357f, 0.0030195293948054314f, 0.0032441799994558096f, 0.0011869262671098113f, 0.0028958087787032127f, 0.003790912451222539f);
static const ai_u16 conv2d_13_t_out_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_13_t_out_0_shape_h_const_u16 = 6;

static const ai_u16 conv2d_14_t_in_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_14_t_in_0_shape_h_const_u16 = 6;
static const ai_u16 conv2d_14_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_14_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_14_t_in_0_shape_ch_const_u16 = 64;
static const ai_u16 conv2d_14_t_out_0_shape_ch_const_u16 = 128;
static const ai_i8 conv2d_14_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_14_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_14_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_14_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_14_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.0066513619385659695f, 0.004037606995552778f, 0.011091353371739388f, 0.0037434345576912165f, 0.004570774268358946f, 0.0062423041090369225f, 0.0030137402936816216f, 0.005145445000380278f, 0.003212784416973591f, 0.0062479195185005665f, 0.004338725470006466f, 0.004943958017975092f, 0.01350701879709959f, 0.006021090783178806f, 0.005740033462643623f, 0.013297016732394695f, 0.007485720794647932f, 0.0062788077630102634f, 0.0036870185285806656f, 0.00995967723429203f, 0.012022930197417736f, 0.0037248716689646244f, 0.00574449310079217f, 0.007253872696310282f, 0.006678817793726921f, 0.003088557394221425f, 0.008070544339716434f, 0.003241293365135789f, 0.004115309100598097f, 0.004220663104206324f, 0.002393917180597782f, 0.0018419009866192937f, 0.00817413255572319f, 0.005614426918327808f, 0.005078562069684267f, 0.006135829258710146f, 0.007894405163824558f, 0.003781117033213377f, 0.004032154101878405f, 0.002194638829678297f, 0.004317351616919041f, 0.003945153206586838f, 0.007485384587198496f, 0.0030168660450726748f, 0.003216234967112541f, 0.009690367616713047f, 0.001800484606064856f, 0.00723456172272563f, 0.004637885373085737f, 0.009760101325809956f, 0.004307121504098177f, 0.0022053446155041456f, 0.00529140280559659f, 0.003186015645042062f, 0.004174215719103813f, 0.008593868464231491f, 0.00272560678422451f, 0.003990503028035164f, 0.01474191714078188f, 0.0063906521536409855f, 0.005581103265285492f, 0.007189593277871609f, 0.0072309584356844425f, 0.006928142625838518f, 0.006913556717336178f, 0.0039062488358467817f, 0.00245075230486691f, 0.0054931254126131535f, 0.005011215806007385f, 0.004259314853698015f, 0.002374933799728751f, 0.0031380821019411087f, 0.008580299094319344f, 0.00575236277654767f, 0.0035630965139716864f, 0.0072793676517903805f, 0.005901141557842493f, 0.006654185708612204f, 0.002605960238724947f, 0.005114879459142685f, 0.004738385323435068f, 0.0037764813750982285f, 0.00884983129799366f, 0.004671973176300526f, 0.0032927808351814747f, 0.0049963826313614845f, 0.003481463994830847f, 0.002856323029845953f, 0.011748782359063625f, 0.003976587206125259f, 0.0034518027678132057f, 0.0028387766797095537f, 0.002283161971718073f, 0.004526335280388594f, 0.015919316560029984f, 0.004158142954111099f, 0.003531078575178981f, 0.0035062823444604874f, 0.002768595702946186f, 0.003248237306252122f, 0.005446490831673145f, 0.007277602329850197f, 0.002600095234811306f, 0.004427905660122633f, 0.009066294878721237f, 0.005694472696632147f, 0.0036942081060260534f, 0.010307654738426208f, 0.005630597472190857f, 0.0037153400480747223f, 0.003997271414846182f, 0.006690087728202343f, 0.007842300459742546f, 0.006935846526175737f, 0.006822327617555857f, 0.002814600709825754f, 0.004127690568566322f, 0.0029065303970128298f, 0.005524706095457077f, 0.002864043926820159f, 0.002837877022102475f, 0.008386104367673397f, 0.007796363439410925f, 0.008861743845045567f, 0.008758875541388988f, 0.003551139961928129f, 0.00502815330401063f, 0.006198485381901264f);
static const ai_layer_format_type conv2d_14_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME;


static const ai_u16 conv2d_15_t_in_0_shape_w_const_u16 = 8;
static const ai_u16 conv2d_15_t_in_0_shape_h_const_u16 = 8;
static const ai_u16 conv2d_15_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_15_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_15_l_stride_0_const_u16 = 1;
static const ai_i8 conv2d_15_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_15_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_15_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_15_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_15_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.008211882784962654f, 0.005804175511002541f, 0.005779430735856295f, 0.015121588483452797f, 0.013626664876937866f, 0.0029273838736116886f, 0.016998905688524246f, 0.016654696315526962f, 0.019544297829270363f, 0.011716966517269611f, 0.008933908306062222f, 0.022582542151212692f, 0.005743527784943581f, 0.003647763980552554f, 0.012953336350619793f, 0.006414925213903189f, 0.01157495565712452f, 0.00608860282227397f, 0.011526552960276604f, 0.006318529136478901f, 0.0017540458356961608f, 0.011935671791434288f, 0.014013703912496567f, 0.009352164342999458f, 0.009602264501154423f, 0.010766393505036831f, 0.003956781234592199f, 0.01563957892358303f, 0.010315715335309505f, 0.0277642160654068f, 0.010207363404333591f, 0.029523149132728577f, 0.009906623512506485f, 0.014866316691040993f, 0.007612362504005432f, 0.008964374661445618f, 0.008514427579939365f, 0.00746386032551527f, 0.018265392631292343f, 0.0215010829269886f, 0.007951166480779648f, 0.015741415321826935f, 0.00796101987361908f, 0.010119762271642685f, 0.013125792145729065f, 0.007151440717279911f, 0.008853038772940636f, 0.014911118894815445f, 0.009311331436038017f, 0.005859367549419403f, 0.007574351504445076f, 0.012510407716035843f, 0.008111578412353992f, 0.012126854620873928f, 0.0138401435688138f, 0.002645723521709442f, 0.026900257915258408f, 0.016606464982032776f, 0.004685855470597744f, 0.006631459575146437f, 0.009957012720406055f, 0.009034167043864727f, 0.012106223031878471f, 0.00866757333278656f, 0.009395262226462364f, 0.007676728069782257f, 0.016337858512997627f, 0.009943808428943157f, 0.01123636681586504f, 0.02221173234283924f, 0.015920666977763176f, 0.010433809831738472f, 0.0067878528498113155f, 0.013248243369162083f, 0.0143516780808568f, 0.007386621553450823f, 0.007598624099045992f, 0.016192356124520302f, 0.011584663763642311f, 0.008469297550618649f, 0.00790467206388712f, 0.009693674743175507f, 0.017902962863445282f, 0.017865510657429695f, 0.007451575715094805f, 0.006343997549265623f, 0.010390574112534523f, 0.007973245345056057f, 0.007074348162859678f, 0.00764866778627038f, 0.014550508931279182f, 0.01918572001159191f, 0.024541806429624557f, 0.01110859401524067f, 0.004962810780853033f, 0.008167454041540623f, 0.010672939009964466f, 0.0060004498809576035f, 0.009990250691771507f, 0.00888204574584961f, 0.018995415419340134f, 0.011532076634466648f, 0.009860539808869362f, 0.012482660822570324f, 0.007577618584036827f, 0.00923950131982565f, 0.016108624637126923f, 0.008507419377565384f, 0.011666899546980858f, 0.008712551556527615f, 0.00612102635204792f, 0.00898473709821701f, 0.008794574066996574f, 0.011295299045741558f, 0.00907120667397976f, 0.008909676223993301f, 0.021290840581059456f, 0.010283874347805977f, 0.01649119332432747f, 0.011028697714209557f, 0.00945885106921196f, 0.00773232989013195f, 0.013238690793514252f, 0.004811860155314207f, 0.003273804672062397f, 0.013628329150378704f, 0.021509379148483276f, 0.005514621268957853f);
static const ai_u16 conv2d_15_t_out_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_15_t_out_0_shape_h_const_u16 = 6;

static const ai_u16 conv2d_16_t_in_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_16_t_in_0_shape_h_const_u16 = 6;
static const ai_u16 conv2d_16_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_16_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_16_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_16_t_out_0_shape_ch_const_u16 = 128;
static const ai_i8 conv2d_16_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_16_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_16_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_16_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_16_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.002571230288594961f, 0.005060975439846516f, 0.0030095383990556f, 0.004030689597129822f, 0.0057168821804225445f, 0.0038083589170128107f, 0.010487230494618416f, 0.004608646966516972f, 0.004270799458026886f, 0.0017768463585525751f, 0.005066653713583946f, 0.004849362187087536f, 0.004825311247259378f, 0.005348590202629566f, 0.010922201909124851f, 0.0031767566688358784f, 0.0008840948576107621f, 0.0032326646614819765f, 0.0030970703810453415f, 0.0023283769842237234f, 0.0033815926872193813f, 0.003456590697169304f, 0.005750820506364107f, 0.005158281419426203f, 0.0021237998735159636f, 0.003950686659663916f, 0.0031266044825315475f, 0.004033740609884262f, 0.010054065845906734f, 0.0059295822866261005f, 0.005315398797392845f, 0.005073134321719408f, 0.004383583087474108f, 0.002928911941125989f, 0.003952703904360533f, 0.0025066954549402f, 0.006157456897199154f, 0.0035726597998291254f, 0.003928289748728275f, 0.005250236485153437f, 0.0025087962858378887f, 0.001242743106558919f, 0.0025028844829648733f, 0.0028147774282842875f, 0.006610851269215345f, 0.008296475745737553f, 0.0021808987949043512f, 0.002224258380010724f, 0.0038017132319509983f, 0.004634334240108728f, 0.0029763649217784405f, 0.002501934999600053f, 0.006016110070049763f, 0.00300745852291584f, 0.004450577311217785f, 0.002963455393910408f, 0.002804222982376814f, 0.006077996920794249f, 0.003000959986820817f, 0.008187279105186462f, 0.0035881309304386377f, 0.0030198683962225914f, 0.003439607098698616f, 0.004007155075669289f, 0.015733009204268456f, 0.004174367990344763f, 0.0031469056848436594f, 0.0069993338547647f, 0.0027444076258689165f, 0.0025483176577836275f, 0.006361459847539663f, 0.005286817904561758f, 0.00494741927832365f, 0.003933676518499851f, 0.006297151558101177f, 0.003738461760804057f, 0.00595729798078537f, 0.005619688890874386f, 0.0032759401947259903f, 0.004749722313135862f, 0.003459248226135969f, 0.0033457723911851645f, 0.005388213787227869f, 0.0021699005737900734f, 0.006559659261256456f, 0.0025653268676251173f, 0.004183252342045307f, 0.005264387000352144f, 0.00517550902441144f, 0.0009105721837840974f, 0.0025012269616127014f, 0.004793008789420128f, 0.0028320057317614555f, 0.003850986948236823f, 0.006303500384092331f, 0.003268108470365405f, 0.0008416307391598821f, 0.0019421468023210764f, 0.00218567019328475f, 0.006200122181326151f, 0.0067154522985219955f, 0.005999331828206778f, 0.00307281780987978f, 0.004736572038382292f, 0.003383729374036193f, 0.0011923228157684207f, 0.006091065239161253f, 0.0019406321225687861f, 0.002464815741404891f, 0.003477965947240591f, 0.004521891940385103f, 0.006868275348097086f, 0.010323066264390945f, 0.004923890810459852f, 0.00630002748221159f, 0.0029079224914312363f, 0.0015723408432677388f, 0.006536762695759535f, 0.003862731857225299f, 0.003028305945917964f, 0.00479144137352705f, 0.006366831250488758f, 0.008660967461764812f, 0.002301269443705678f, 0.004578868392854929f, 0.004389912821352482f, 0.003503104206174612f, 0.00320574757643044f);
static const ai_layer_format_type conv2d_16_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME;


static const ai_u16 conv2d_17_t_in_0_shape_w_const_u16 = 8;
static const ai_u16 conv2d_17_t_in_0_shape_h_const_u16 = 8;
static const ai_u16 conv2d_17_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_17_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_17_l_stride_0_const_u16 = 1;
static const ai_i8 conv2d_17_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_17_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_17_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_17_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_17_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.011028792709112167f, 0.007497292011976242f, 0.007611552719026804f, 0.006728389300405979f, 0.004889924079179764f, 0.010993033647537231f, 0.006218814756721258f, 0.004473233595490456f, 0.007323253434151411f, 0.003992240875959396f, 0.00445095170289278f, 0.0057337405160069466f, 0.006827321369200945f, 0.007579785771667957f, 0.0019807128701359034f, 0.007438173051923513f, 0.04312923178076744f, 0.007446633651852608f, 0.014224806800484657f, 0.01195716205984354f, 0.010089335963129997f, 0.009321614168584347f, 0.01744115725159645f, 0.005365705583244562f, 0.017592230811715126f, 0.01482192613184452f, 0.013535639271140099f, 0.007162952329963446f, 0.003890319261699915f, 0.008115332573652267f, 0.002589669544249773f, 0.00653550261631608f, 0.003443548223003745f, 0.017949366942048073f, 0.006773846689611673f, 0.013017947785556316f, 0.005324455443769693f, 0.008246008306741714f, 0.009293985553085804f, 0.006310650147497654f, 0.010609835386276245f, 0.017772283405065536f, 0.008397571742534637f, 0.00975026749074459f, 0.0037928412202745676f, 0.004918352235108614f, 0.009558427147567272f, 0.012804282829165459f, 0.007438180968165398f, 0.0018758416408672929f, 0.00962921418249607f, 0.008737386204302311f, 0.005852796137332916f, 0.006687043234705925f, 0.007810389623045921f, 0.008972985669970512f, 0.006901663262397051f, 0.007395608350634575f, 0.0106112165376544f, 0.003641919232904911f, 0.007240223698318005f, 0.00901157595217228f, 0.0031664969865232706f, 0.0018444218439981341f, 0.002448386512696743f, 0.00445430027320981f, 0.005906199105083942f, 0.006239529699087143f, 0.007060209754854441f, 0.012134845368564129f, 0.008705639280378819f, 0.00788514781743288f, 0.006542914547026157f, 0.007969225756824017f, 0.0021935193799436092f, 0.0040710484609007835f, 0.005702721420675516f, 0.003980461973696947f, 0.0035169138573110104f, 0.008107216097414494f, 0.004520035348832607f, 0.008610241115093231f, 0.005910331849008799f, 0.014254426583647728f, 0.007670549210160971f, 0.005013674963265657f, 0.009003469720482826f, 0.007979015819728374f, 0.007798205595463514f, 0.04962129518389702f, 0.008293773047626019f, 0.005385487340390682f, 0.009638851508498192f, 0.007458302658051252f, 0.004635000601410866f, 0.004675270989537239f, 0.03055960312485695f, 0.017241207882761955f, 0.003697976004332304f, 0.004474058281630278f, 0.002266989555209875f, 0.005715217906981707f, 0.009279430843889713f, 0.00484487134963274f, 0.007861212827265263f, 0.03026166930794716f, 0.005038427654653788f, 0.01589072309434414f, 0.011300373822450638f, 0.009136387147009373f, 0.0063699400052428246f, 0.003967170137912035f, 0.007633125875145197f, 0.005936052184551954f, 0.0028180659282952547f, 0.005345678422600031f, 0.022691741585731506f, 0.0023340247571468353f, 0.012586178258061409f, 0.011416741646826267f, 0.0064031705260276794f, 0.005399235524237156f, 0.012278733775019646f, 0.008370812982320786f, 0.003162648994475603f, 0.006844584364444017f, 0.006867370568215847f, 0.010409880429506302f);
static const ai_u16 conv2d_17_t_out_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_17_t_out_0_shape_h_const_u16 = 6;

static const ai_u16 conv2d_18_t_in_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_18_t_in_0_shape_h_const_u16 = 6;
static const ai_u16 conv2d_18_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_18_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_18_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_18_t_out_0_shape_ch_const_u16 = 128;
static const ai_i8 conv2d_18_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_18_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_18_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_18_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_18_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.0021020325366407633f, 0.004785008262842894f, 0.008547225967049599f, 0.004815118387341499f, 0.002633098978549242f, 0.00245464569889009f, 0.0022943145595490932f, 0.0019148180726915598f, 0.003643771866336465f, 0.006738822907209396f, 0.004737157840281725f, 0.001643901108764112f, 0.004303932189941406f, 0.008556274697184563f, 0.0026136799715459347f, 0.007092485204339027f, 0.004624517634510994f, 0.0031430795788764954f, 0.00621033925563097f, 0.002558930777013302f, 0.002027602633461356f, 0.004654260352253914f, 0.005419128108769655f, 0.004350801929831505f, 0.004688791930675507f, 0.005122332368046045f, 0.004075256176292896f, 0.008036376908421516f, 0.0024131617974489927f, 0.005838525481522083f, 0.0030507175251841545f, 0.006232778076082468f, 0.0023272125981748104f, 0.005156779661774635f, 0.002893253695219755f, 0.0027373747434467077f, 0.005107662174850702f, 0.004961777478456497f, 0.002719530835747719f, 0.004166542552411556f, 0.004297114443033934f, 0.011042074300348759f, 0.007410717662423849f, 0.003982382360845804f, 0.003711243160068989f, 0.0030177757143974304f, 0.0053493729792535305f, 0.0031593546736985445f, 0.0024487345945090055f, 0.0057023814879357815f, 0.002530838595703244f, 0.0041829985566437244f, 0.0034362913575023413f, 0.003503126557916403f, 0.005367386154830456f, 0.0021374784409999847f, 0.00276822317391634f, 0.004174499306827784f, 0.004291425459086895f, 0.00338138360530138f, 0.003578594885766506f, 0.0058858636766672134f, 0.0037974554579705f, 0.0027476134710013866f, 0.0034030957613140345f, 0.004515775479376316f, 0.0018910268554463983f, 0.002643933752551675f, 0.003354150801897049f, 0.004534977488219738f, 0.0017639645375311375f, 0.005434640683233738f, 0.004651993978768587f, 0.0026933406479656696f, 0.006727903615683317f, 0.002642026636749506f, 0.00831226259469986f, 0.004252343904227018f, 0.002980169141665101f, 0.0031375756952911615f, 0.0040182992815971375f, 0.005174861755222082f, 0.0036786296404898167f, 0.0055337646044790745f, 0.005113794468343258f, 0.005592774134129286f, 0.002448061481118202f, 0.005866634659469128f, 0.005219202488660812f, 0.0031382429879158735f, 0.0042399149388074875f, 0.003350658342242241f, 0.0029712405521422625f, 0.0030123156029731035f, 0.005411332473158836f, 0.003999275155365467f, 0.003445903304964304f, 0.0017781746573746204f, 0.004474332556128502f, 0.00414271280169487f, 0.002060998696833849f, 0.006044961512088776f, 0.004970912355929613f, 0.004080004524439573f, 0.002907500136643648f, 0.0037946433294564486f, 0.007172055076807737f, 0.006648891605436802f, 0.008545350283384323f, 0.004761356860399246f, 0.004475975409150124f, 0.002592124044895172f, 0.007630470208823681f, 0.006597232539206743f, 0.005845258478075266f, 0.003042733995243907f, 0.0031475285068154335f, 0.0038859897758811712f, 0.005236499477177858f, 0.0022576074115931988f, 0.0034013064578175545f, 0.0036021932028234005f, 0.00442475825548172f, 0.004802385810762644f, 0.004208060912787914f, 0.0020503802224993706f, 0.0033861438278108835f, 0.002278778003528714f);
static const ai_layer_format_type conv2d_18_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME;


static const ai_u16 conv2d_19_t_in_0_shape_w_const_u16 = 8;
static const ai_u16 conv2d_19_t_in_0_shape_h_const_u16 = 8;
static const ai_u16 conv2d_19_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_19_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_19_l_stride_0_const_u16 = 1;
static const ai_i8 conv2d_19_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_19_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_19_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_19_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_19_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.00940218660980463f, 0.007683648727834225f, 0.0016628882149234414f, 0.008105889894068241f, 0.009005993604660034f, 0.0073199146427214146f, 0.01609008200466633f, 0.01142360083758831f, 0.0040143439546227455f, 0.009302524849772453f, 0.0029802839271724224f, 0.017300710082054138f, 0.0019627853762358427f, 0.0028436717111617327f, 0.010171793401241302f, 0.005337598267942667f, 0.0036220781039446592f, 0.012351086363196373f, 0.004851920530200005f, 0.009427421726286411f, 0.018163131549954414f, 0.0037573915906250477f, 0.006605145055800676f, 0.004257692489773035f, 0.007522867992520332f, 0.00360338413156569f, 0.005052405875176191f, 0.0031376152765005827f, 0.010068544186651707f, 0.00612406013533473f, 0.007112142629921436f, 0.005093894433230162f, 0.01666969060897827f, 0.004940859042108059f, 0.018360348418354988f, 0.007286367937922478f, 0.003202797845005989f, 0.006801526062190533f, 0.013684648089110851f, 0.004060079343616962f, 0.013456086628139019f, 0.003447561524808407f, 0.0034289604518562555f, 0.007493904326111078f, 0.0020911600440740585f, 0.008424484170973301f, 0.0021083715837448835f, 0.007618721574544907f, 0.005371768958866596f, 0.009261909872293472f, 0.013966886326670647f, 0.009285667911171913f, 0.007598911877721548f, 0.00768000865355134f, 0.005096912384033203f, 0.008211564272642136f, 0.011625817976891994f, 0.008122405037283897f, 0.004398839548230171f, 0.00701766787096858f, 0.007303293794393539f, 0.005423248279839754f, 0.0023247594945132732f, 0.007008087821304798f, 0.006536130793392658f, 0.0038524207193404436f, 0.01018993929028511f, 0.006060622166842222f, 0.004453789442777634f, 0.005507645197212696f, 0.008976812474429607f, 0.008422790095210075f, 0.003491469193249941f, 0.006356858182698488f, 0.005880567245185375f, 0.010333078913390636f, 0.0037260965909808874f, 0.007442969363182783f, 0.004976315423846245f, 0.003269523149356246f, 0.00359459244646132f, 0.0036972800735384226f, 0.006628309842199087f, 0.003826502477750182f, 0.003355461172759533f, 0.0015949757071211934f, 0.009301098063588142f, 0.0039180852472782135f, 0.008656236343085766f, 0.010214511305093765f, 0.0036050083581358194f, 0.006624788977205753f, 0.007937321439385414f, 0.01377849094569683f, 0.003973499406129122f, 0.006938635837286711f, 0.007417881395667791f, 0.014160818420350552f, 0.004102807957679033f, 0.008151727728545666f, 0.021187013015151024f, 0.0047434731386601925f, 0.009956387802958488f, 0.008314919658005238f, 0.007056005299091339f, 0.003889965359121561f, 0.0040559424087405205f, 0.0020483711268752813f, 0.004084551241248846f, 0.003569400869309902f, 0.004728786647319794f, 0.009475034661591053f, 0.004249792080372572f, 0.002922853920608759f, 0.0037044298369437456f, 0.006259028799831867f, 0.010465332306921482f, 0.006391341798007488f, 0.0022170464508235455f, 0.009072048589587212f, 0.008481580764055252f, 0.006903845816850662f, 0.0038943206891417503f, 0.006784906145185232f, 0.01220062654465437f, 0.009703957475721836f, 0.011720732785761356f, 0.009375360794365406f);
static const ai_u16 conv2d_19_t_out_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_19_t_out_0_shape_h_const_u16 = 6;

static const ai_u16 conv2d_20_t_in_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_20_t_in_0_shape_h_const_u16 = 6;
static const ai_u16 conv2d_20_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_20_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_20_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_20_t_out_0_shape_ch_const_u16 = 128;
static const ai_i8 conv2d_20_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_20_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_20_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_20_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_20_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.0019929714035242796f, 0.0032532881014049053f, 0.003116070060059428f, 0.002710142871364951f, 0.0037702489644289017f, 0.002667501801624894f, 0.004135835915803909f, 0.00397553900256753f, 0.005340426694601774f, 0.002503311727195978f, 0.00393383763730526f, 0.004335357341915369f, 0.0029420035425573587f, 0.005151457618921995f, 0.007017998024821281f, 0.006584127899259329f, 0.005005398765206337f, 0.004163256846368313f, 0.004149144981056452f, 0.004211693536490202f, 0.0016324801836162806f, 0.003193276934325695f, 0.005873987451195717f, 0.005112827755510807f, 0.0065538762137293816f, 0.004921135026961565f, 0.004186972975730896f, 0.00342574086971581f, 0.003916165325790644f, 0.0036937848199158907f, 0.004014742095023394f, 0.002714017638936639f, 0.0043623424135148525f, 0.0031745443120598793f, 0.0037067001685500145f, 0.004579461179673672f, 0.00449141301214695f, 0.0014893545303493738f, 0.0034638892393559217f, 0.005170417949557304f, 0.006042467895895243f, 0.0038712862879037857f, 0.004640554543584585f, 0.0040543475188314915f, 0.003323841141536832f, 0.010738076642155647f, 0.00912907999008894f, 0.005052962340414524f, 0.004448434803634882f, 0.003254534676671028f, 0.0035658194683492184f, 0.0048674363642930984f, 0.007016083225607872f, 0.0010557578643783927f, 0.005873163230717182f, 0.009940889663994312f, 0.0007338892901316285f, 0.003959746100008488f, 0.006838328670710325f, 0.0036013408098369837f, 0.003052342915907502f, 0.004716099705547094f, 0.0024287751875817776f, 0.0024542915634810925f, 0.003063856391236186f, 0.005411617457866669f, 0.0034149987623095512f, 0.0034353306982666254f, 0.002713473280891776f, 0.0052262102253735065f, 0.004444868303835392f, 0.005491574294865131f, 0.0024872850626707077f, 0.0058844564482569695f, 0.002748869126662612f, 0.004796504508703947f, 0.003266888437792659f, 0.006091961171478033f, 0.002809328492730856f, 0.0043252501636743546f, 0.004944084212183952f, 0.004588402807712555f, 0.006461718585342169f, 0.005608558654785156f, 0.002794253872707486f, 0.005289399065077305f, 0.005286952015012503f, 0.0025911331176757812f, 0.005470311269164085f, 0.003773137228563428f, 0.007878432981669903f, 0.0045717512257397175f, 0.0033967935014516115f, 0.0035626681055873632f, 0.010233072564005852f, 0.003858419368043542f, 0.007645607925951481f, 0.0031366446055471897f, 0.002942749997600913f, 0.005693226587027311f, 0.003528781235218048f, 0.0035807497333735228f, 0.002884494373574853f, 0.00862874649465084f, 0.0049027553759515285f, 0.0035134111531078815f, 0.0018570838728919625f, 0.006366550922393799f, 0.004606486298143864f, 0.004548914730548859f, 0.004141499288380146f, 0.002246007788926363f, 0.00244074035435915f, 0.004753575194627047f, 0.00397101603448391f, 0.002632135758176446f, 0.003646010998636484f, 0.0032311640679836273f, 0.0034826090559363365f, 0.006763842422515154f, 0.0035688811913132668f, 0.002508478472009301f, 0.0058723678812384605f, 0.003405896946787834f, 0.0036069226916879416f, 0.0045934016816318035f, 0.0035063293762505054f, 0.0034541673958301544f);
static const ai_layer_format_type conv2d_20_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME;


static const ai_u16 conv2d_21_t_in_0_shape_w_const_u16 = 8;
static const ai_u16 conv2d_21_t_in_0_shape_h_const_u16 = 8;
static const ai_u16 conv2d_21_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_21_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_21_l_stride_0_const_u16 = 1;
static const ai_i8 conv2d_21_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_21_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_21_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_21_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_21_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.00919430237263441f, 0.0048295254819095135f, 0.00887539703398943f, 0.005716288927942514f, 0.009386248886585236f, 0.008175989612936974f, 0.008860193192958832f, 0.006138369906693697f, 0.004898617044091225f, 0.006095621269196272f, 0.007387759629637003f, 0.008978682570159435f, 0.00819869339466095f, 0.0029492450412362814f, 0.004568313714116812f, 0.007157162297517061f, 0.009275910444557667f, 0.0030208483804017305f, 0.0052767107263207436f, 0.004978775046765804f, 0.011307076551020145f, 0.006861343048512936f, 0.0041793459095060825f, 0.007098894100636244f, 0.0029465302359312773f, 0.002977882046252489f, 0.005183171480894089f, 0.004832231439650059f, 0.007872129790484905f, 0.0038909956347197294f, 0.0036544420290738344f, 0.0074892183765769005f, 0.005785500630736351f, 0.005990097764879465f, 0.0059801070019602776f, 0.004449592903256416f, 0.0034242356196045876f, 0.017465028911828995f, 0.008546063676476479f, 0.003936742432415485f, 0.003311295760795474f, 0.007821383886039257f, 0.0032037210185080767f, 0.0045337071642279625f, 0.008511754684150219f, 0.0029117483645677567f, 0.00345883728004992f, 0.006027742754667997f, 0.0030273140873759985f, 0.007169301155954599f, 0.008741569705307484f, 0.007370992098003626f, 0.006773733999580145f, 0.02105969749391079f, 0.008366839028894901f, 0.004726594779640436f, 0.044605500996112823f, 0.0055283717811107635f, 0.001522295642644167f, 0.006273816805332899f, 0.00883184839040041f, 0.007616150658577681f, 0.009056992828845978f, 0.014165783300995827f, 0.006107107270509005f, 0.006732625421136618f, 0.008064133115112782f, 0.012486733496189117f, 0.012795697897672653f, 0.0013037266908213496f, 0.005556698888540268f, 0.007672971114516258f, 0.007764353882521391f, 0.005680509842932224f, 0.007267699111253023f, 0.006107185501605272f, 0.004027707502245903f, 0.008570035919547081f, 0.016104446724057198f, 0.0013022272614762187f, 0.00414649024605751f, 0.004335611592978239f, 0.003584899939596653f, 0.005041684955358505f, 0.009539295919239521f, 0.008102222345769405f, 0.0037059166934341192f, 0.013921529054641724f, 0.0060076238587498665f, 0.0024971263483166695f, 0.004188274033367634f, 0.004975637886673212f, 0.006197087466716766f, 0.007052822504192591f, 0.001615850254893303f, 0.01067026425153017f, 0.0039161196909844875f, 0.00925983302295208f, 0.00756675424054265f, 0.002925806911662221f, 0.00816352479159832f, 0.0058239479549229145f, 0.003806472523137927f, 0.0023870980367064476f, 0.007314259186387062f, 0.004571737255901098f, 0.013495123945176601f, 0.001521449419669807f, 0.0032326688524335623f, 0.006554385647177696f, 0.004919907543808222f, 0.010239481925964355f, 0.008355624042451382f, 0.015210535377264023f, 0.004942888859659433f, 0.008917054161429405f, 0.002037851372733712f, 0.004504099953919649f, 0.005647528450936079f, 0.0017752677667886019f, 0.00705156521871686f, 0.008731640875339508f, 0.0025521814823150635f, 0.008070036768913269f, 0.0061227926053106785f, 0.00884965155273676f, 0.009185532107949257f, 0.0038449533749371767f);
static const ai_u16 conv2d_21_t_out_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_21_t_out_0_shape_h_const_u16 = 6;

static const ai_u16 conv2d_22_t_in_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_22_t_in_0_shape_h_const_u16 = 6;
static const ai_u16 conv2d_22_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_22_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_22_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_22_t_out_0_shape_ch_const_u16 = 128;
static const ai_i8 conv2d_22_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_22_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_22_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_22_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_22_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.004267256241291761f, 0.02084909752011299f, 0.004067681264132261f, 0.004112328868359327f, 0.003498408477753401f, 0.0021200780756771564f, 0.003794614225625992f, 0.004293031059205532f, 0.007700311951339245f, 0.0034483904018998146f, 0.0026349874678999186f, 0.0033933278173208237f, 0.004171374719589949f, 0.005798851139843464f, 0.004214313346892595f, 0.008325453847646713f, 0.031037531793117523f, 0.003446464193984866f, 0.003218448953703046f, 0.0035065405536442995f, 0.0025831281673163176f, 0.005011284723877907f, 0.004382074810564518f, 0.004359313752502203f, 0.0032500657252967358f, 0.003477511228993535f, 0.0036843956913799047f, 0.004343567416071892f, 0.003217986086383462f, 0.004059264902025461f, 0.005398655775934458f, 0.00477826502174139f, 0.00560938473790884f, 0.0051791914738714695f, 0.003150852397084236f, 0.005852194968611002f, 0.005443992558866739f, 0.004126205109059811f, 0.001720698201097548f, 0.0024331489112228155f, 0.005974344909191132f, 0.0021678234916180372f, 0.004811855498701334f, 0.005675675813108683f, 0.003199388738721609f, 0.006846202537417412f, 0.0029797700699418783f, 0.015954654663801193f, 0.004171476233750582f, 0.004505652468651533f, 0.007675083354115486f, 0.004884324036538601f, 0.0037750289775431156f, 0.003177755745127797f, 0.003273965558037162f, 0.0025474857538938522f, 0.008774369955062866f, 0.005424987990409136f, 0.003685547038912773f, 0.005583612248301506f, 0.009202402085065842f, 0.004550501704216003f, 0.003858323907479644f, 0.0038628047332167625f, 0.0052320766262710094f, 0.004019783344119787f, 0.0038717493880540133f, 0.003896299982443452f, 0.0036985818296670914f, 0.00579307833686471f, 0.006390633527189493f, 0.0034949579276144505f, 0.004576193634420633f, 0.007515012752264738f, 0.002494869753718376f, 0.004942063242197037f, 0.0035720220766961575f, 0.005245881155133247f, 0.004095668438822031f, 0.0022936377208679914f, 0.005931188818067312f, 0.0033316377084702253f, 0.003329804167151451f, 0.003961141686886549f, 0.004767561797052622f, 0.002683431375771761f, 0.0036173956468701363f, 0.0042928061448037624f, 0.002976121613755822f, 0.006891350727528334f, 0.004687690641731024f, 0.003733702003955841f, 0.004797056317329407f, 0.004996566101908684f, 0.004598970524966717f, 0.002379324985668063f, 0.002521755639463663f, 0.010367324575781822f, 0.004305526614189148f, 0.003981760237365961f, 0.002590098651126027f, 0.003803086932748556f, 0.0053430283442139626f, 0.0038191520143300295f, 0.003849399508908391f, 0.0034217764623463154f, 0.004064116161316633f, 0.010812138207256794f, 0.00414237892255187f, 0.005350998602807522f, 0.004998859949409962f, 0.0036082470323890448f, 0.004348705988377333f, 0.004376755096018314f, 0.002091575413942337f, 0.005119503941386938f, 0.004132203757762909f, 0.0050943465903401375f, 0.009199021384119987f, 0.004438572097569704f, 0.004084366839379072f, 0.004085733089596033f, 0.005376520566642284f, 0.00818298663944006f, 0.003001129487529397f, 0.00426435936242342f, 0.0033122976310551167f, 0.003299917094409466f);
static const ai_layer_format_type conv2d_22_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME;


static const ai_u16 conv2d_23_t_in_0_shape_w_const_u16 = 8;
static const ai_u16 conv2d_23_t_in_0_shape_h_const_u16 = 8;
static const ai_u16 conv2d_23_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_23_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_23_l_stride_0_const_u16 = 1;
static const ai_i8 conv2d_23_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_23_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_23_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_23_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_23_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.004877516068518162f, 0.003458605380728841f, 0.00493833189830184f, 0.0063296593725681305f, 0.008142861537635326f, 0.009910248219966888f, 0.003956203814595938f, 0.008323040790855885f, 0.0014875526539981365f, 0.006319410167634487f, 0.012999820522964f, 0.006151644047349691f, 0.005861697718501091f, 0.005266399588435888f, 0.005886018741875887f, 0.008068847469985485f, 0.0015471619553864002f, 0.0019386174390092492f, 0.004567357711493969f, 0.008108828216791153f, 0.013886397704482079f, 0.002952303970232606f, 0.007103803101927042f, 0.0026835943572223186f, 0.005676522385329008f, 0.004529466386884451f, 0.002750230021774769f, 0.005049766506999731f, 0.00379987177439034f, 0.001489888527430594f, 0.007786499802023172f, 0.006831815931946039f, 0.00836001057177782f, 0.0030366522260010242f, 0.006959215737879276f, 0.00807971227914095f, 0.0058846850879490376f, 0.006454420741647482f, 0.009704909287393093f, 0.004511368926614523f, 0.0017627220368012786f, 0.010906773619353771f, 0.0075240181758999825f, 0.002147958381101489f, 0.0063536567613482475f, 0.009699753485620022f, 0.005300053395330906f, 0.003503713058307767f, 0.0070981853641569614f, 0.009580688551068306f, 0.0016720951534807682f, 0.009419519454240799f, 0.004808962345123291f, 0.006272386759519577f, 0.005398163106292486f, 0.01100919023156166f, 0.0020472167525440454f, 0.005513051990419626f, 0.006701522506773472f, 0.004390287678688765f, 0.003792515257373452f, 0.008015074767172337f, 0.003083497751504183f, 0.003240840742364526f, 0.004243234638124704f, 0.005510370247066021f, 0.005712226033210754f, 0.003784982720389962f, 0.003942000214010477f, 0.0078321173787117f, 0.002294593257829547f, 0.00639299163594842f, 0.002624344313517213f, 0.0025118722114712f, 0.007291258312761784f, 0.0027781473472714424f, 0.013637366704642773f, 0.007737878710031509f, 0.0036014197394251823f, 0.008545483462512493f, 0.005887860432267189f, 0.008836339227855206f, 0.008200016804039478f, 0.0023183682933449745f, 0.007459381595253944f, 0.006937501486390829f, 0.004793634172528982f, 0.002823497401550412f, 0.004700309131294489f, 0.0038578433450311422f, 0.005483636166900396f, 0.004688425920903683f, 0.005221359431743622f, 0.007134092506021261f, 0.009799265302717686f, 0.008074100129306316f, 0.00940951332449913f, 0.0036414621863514185f, 0.006098742131143808f, 0.0013879358302801847f, 0.013887766748666763f, 0.006689070723950863f, 0.008873019367456436f, 0.0070518855936825275f, 0.011109032668173313f, 0.009315093979239464f, 0.0071471454575657845f, 0.001458692830055952f, 0.0072400616481900215f, 0.0018809032626450062f, 0.005021166056394577f, 0.007260097190737724f, 0.007389923091977835f, 0.0033892642240971327f, 0.007936717942357063f, 0.0022701206617057323f, 0.0038649816997349262f, 0.007960756309330463f, 0.0019328204216435552f, 0.005797108169645071f, 0.003919374197721481f, 0.004998962394893169f, 0.00500583928078413f, 0.005855971481651068f, 0.014588327147066593f, 0.0016473954310640693f, 0.004971941467374563f, 0.007207839749753475f);
static const ai_u16 conv2d_23_t_out_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_23_t_out_0_shape_h_const_u16 = 6;

static const ai_u16 conv2d_24_t_in_0_shape_w_const_u16 = 6;
static const ai_u16 conv2d_24_t_in_0_shape_h_const_u16 = 6;
static const ai_u16 conv2d_24_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_24_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_24_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_24_t_out_0_shape_ch_const_u16 = 128;
static const ai_i8 conv2d_24_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_24_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_24_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_24_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_24_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.003706417977809906f, 0.003457875456660986f, 0.0034997733309865f, 0.003968811593949795f, 0.002934318734332919f, 0.004951630253344774f, 0.003732923185452819f, 0.004554430488497019f, 0.004189461935311556f, 0.004775303415954113f, 0.0030985239427536726f, 0.003521756734699011f, 0.002800860907882452f, 0.003738667583093047f, 0.00770292803645134f, 0.0033531279768794775f, 0.003265857696533203f, 0.003243182087317109f, 0.0035678199492394924f, 0.006825407966971397f, 0.004333831835538149f, 0.0031630441080778837f, 0.00580698112025857f, 0.003368275472894311f, 0.003665309399366379f, 0.0035167394671589136f, 0.0041075111366808414f, 0.004314729478210211f, 0.003063998883590102f, 0.006732241250574589f, 0.003660020884126425f, 0.004270554520189762f, 0.004798739682883024f, 0.004207800142467022f, 0.0034842730965465307f, 0.0028889700770378113f, 0.003928056452423334f, 0.004540903493762016f, 0.0034053425770252943f, 0.004915309604257345f, 0.006494802888482809f, 0.003190298331901431f, 0.004022771026939154f, 0.005162199959158897f, 0.006093703210353851f, 0.01329322624951601f, 0.003514455631375313f, 0.0030071628279983997f, 0.003997320309281349f, 0.0030423966236412525f, 0.0031452039256691933f, 0.003760433057323098f, 0.0037554760929197073f, 0.004556205589324236f, 0.005002646706998348f, 0.0050637563690543175f, 0.004833610728383064f, 0.003919752314686775f, 0.005987279117107391f, 0.004574434366077185f, 0.004248557612299919f, 0.0036972248926758766f, 0.004709892440587282f, 0.004041660111397505f, 0.0034827208146452904f, 0.00394708476960659f, 0.003977611195296049f, 0.00437031639739871f, 0.0023655714467167854f, 0.011069176718592644f, 0.004080630838871002f, 0.004174515604972839f, 0.005221859086304903f, 0.0035867933183908463f, 0.004569549113512039f, 0.004605473019182682f, 0.004523186478763819f, 0.0039774528704583645f, 0.0030273981392383575f, 0.004131716676056385f, 0.003977085463702679f, 0.0056984443217515945f, 0.003281456185504794f, 0.00303557887673378f, 0.0035703019239008427f, 0.006836871150881052f, 0.003202453488484025f, 0.00451393099501729f, 0.0036304041277617216f, 0.004132045898586512f, 0.0047632986679673195f, 0.0035915449261665344f, 0.0028039601165801287f, 0.003278947900980711f, 0.0038020992651581764f, 0.0062745921313762665f, 0.0032110020983964205f, 0.003406885080039501f, 0.002947443863376975f, 0.0037633730098605156f, 0.004057248588651419f, 0.003049336839467287f, 0.0033844609279185534f, 0.0031139173079282045f, 0.004941712133586407f, 0.004457629751414061f, 0.003972034435719252f, 0.003220092738047242f, 0.001759908045642078f, 0.0034949693363159895f, 0.006017887499183416f, 0.002995561109855771f, 0.004413751885294914f, 0.0024508212227374315f, 0.005682845134288073f, 0.003943871706724167f, 0.0031725678127259016f, 0.005955840460956097f, 0.004128655884414911f, 0.002781880786642432f, 0.004598488099873066f, 0.0038738565053790808f, 0.0044386419467628f, 0.014055001549422741f, 0.007141598965972662f, 0.003446955466642976f, 0.004376295953989029f, 0.0028967903926968575f);
static const ai_layer_format_type conv2d_24_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_FIRST_SAME2;


static const ai_u16 conv2d_25_t_in_0_shape_w_const_u16 = 8;
static const ai_u16 conv2d_25_t_in_0_shape_h_const_u16 = 8;
static const ai_u16 conv2d_25_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_25_l_stride_1_const_u16 = 2;
static const ai_u16 conv2d_25_l_stride_0_const_u16 = 2;
static const ai_i8 conv2d_25_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_25_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_25_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_25_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_25_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.0033227538224309683f, 0.0036516578402370214f, 0.0032747951336205006f, 0.0032458032947033644f, 0.0033941862639039755f, 0.0027391528710722923f, 0.0021305985283106565f, 0.0035630930215120316f, 0.0028805441688746214f, 0.004845597315579653f, 0.0022748580668121576f, 0.0037045658100396395f, 0.004112240392714739f, 0.002497682813555002f, 0.0014011935563758016f, 0.0033614046406000853f, 0.002482113428413868f, 0.0027573222760111094f, 0.004827776458114386f, 0.005139636807143688f, 0.003153048222884536f, 0.0037722820416092873f, 0.002646681619808078f, 0.0034555322490632534f, 0.00406392989680171f, 0.00357946939766407f, 0.003178047714754939f, 0.0030583839397877455f, 0.002641453640535474f, 0.0018145381473004818f, 0.003423291025683284f, 0.003936599474400282f, 0.003402635222300887f, 0.004237399436533451f, 0.004455826710909605f, 0.002687541302293539f, 0.0029187528416514397f, 0.00301538803614676f, 0.00314257456921041f, 0.002124643884599209f, 0.001384981325827539f, 0.002725741593167186f, 0.0024296557530760765f, 0.002134878421202302f, 0.0028862119652330875f, 0.0016713130753487349f, 0.0035040390212088823f, 0.004477133043110371f, 0.0028824128676205873f, 0.0030827883165329695f, 0.003682390321046114f, 0.002844227012246847f, 0.005043388810008764f, 0.003379296511411667f, 0.00254472391679883f, 0.003569313557818532f, 0.0034102972131222486f, 0.0037038063164800406f, 0.005030110944062471f, 0.0018304245313629508f, 0.006550660356879234f, 0.00454937806352973f, 0.004991473164409399f, 0.005207212176173925f, 0.002640356309711933f, 0.0036342008970677853f, 0.003946371842175722f, 0.00387434009462595f, 0.005110124591737986f, 0.0040342556312680244f, 0.0026311813853681087f, 0.003967686556279659f, 0.0015864648157730699f, 0.0027784216217696667f, 0.004734352231025696f, 0.0033441551495343447f, 0.0036490866914391518f, 0.003635033033788204f, 0.0023708881344646215f, 0.004146664869040251f, 0.0027421724516898394f, 0.0028617377392947674f, 0.0027136937715113163f, 0.0034111225977540016f, 0.0035395496524870396f, 0.001966791460290551f, 0.0027641344349831343f, 0.00587203074246645f, 0.0035444567911326885f, 0.003946021664887667f, 0.003050526138395071f, 0.0021595994476228952f, 0.004565466195344925f, 0.002363770268857479f, 0.00365904881618917f, 0.002512083388864994f, 0.002716301940381527f, 0.002700395882129669f, 0.0024157497100532055f, 0.0039314208552241325f, 0.004473174922168255f, 0.003051269566640258f, 0.005140041932463646f, 0.004353087395429611f, 0.001956752734258771f, 0.003586572827771306f, 0.0037736741360276937f, 0.005009794607758522f, 0.010076528415083885f, 0.003777132835239172f, 0.0012732240138575435f, 0.003213980933651328f, 0.005133253522217274f, 0.005663298070430756f, 0.0017709379317238927f, 0.0031983312219381332f, 0.004313258919864893f, 0.0018212689319625497f, 0.0033936724066734314f, 0.004863895941525698f, 0.004195042885839939f, 0.002615135395899415f, 0.002942845690995455f, 0.021195827051997185f, 0.0026729321107268333f, 0.0025682314299046993f, 0.0023281613830477f, 0.0035398013424128294f);
static const ai_u16 conv2d_25_t_out_0_shape_w_const_u16 = 3;
static const ai_u16 conv2d_25_t_out_0_shape_h_const_u16 = 3;

static const ai_u16 conv2d_26_t_in_0_shape_w_const_u16 = 3;
static const ai_u16 conv2d_26_t_in_0_shape_h_const_u16 = 3;
static const ai_u16 conv2d_26_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_26_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_26_t_in_0_shape_ch_const_u16 = 128;
static const ai_u16 conv2d_26_t_out_0_shape_ch_const_u16 = 256;
static const ai_i8 conv2d_26_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_26_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_26_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_26_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_26_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.004479466937482357f, 0.003242501989006996f, 0.005109325982630253f, 0.0035745820496231318f, 0.0045214262790977955f, 0.008795700967311859f, 0.0025946542154997587f, 0.00550077436491847f, 0.0033692780416458845f, 0.005718609318137169f, 0.0038867818657308817f, 0.004374200943857431f, 0.005915703251957893f, 0.004736374132335186f, 0.003965318668633699f, 0.003992494661360979f, 0.002707422012463212f, 0.0043149166740477085f, 0.007536412216722965f, 0.0038851641584187746f, 0.0048159523867070675f, 0.009237761609256268f, 0.003480185754597187f, 0.0035562110133469105f, 0.0028829036746174097f, 0.003409096971154213f, 0.0033775148913264275f, 0.004261018242686987f, 0.003469311399385333f, 0.007558825891464949f, 0.005185020621865988f, 0.0038339311722666025f, 0.03181592375040054f, 0.0033426254522055387f, 0.008305510506033897f, 0.002335492055863142f, 0.00252723041921854f, 0.006246703676879406f, 0.004366524051874876f, 0.004165763966739178f, 0.003994967322796583f, 0.006961784791201353f, 0.004729859065264463f, 0.003001019125804305f, 0.003088943660259247f, 0.004730003885924816f, 0.004535384476184845f, 0.004484189208596945f, 0.00400773249566555f, 0.004715851973742247f, 0.004419978708028793f, 0.002652673749253154f, 0.002985709812492132f, 0.005908200517296791f, 0.010937055572867393f, 0.005731124430894852f, 0.0054532322101294994f, 0.004147334489971399f, 0.0043212901800870895f, 0.004186439327895641f, 0.005010045133531094f, 0.0034093521535396576f, 0.004497875459492207f, 0.005904593039304018f, 0.003936442080885172f, 0.004970264155417681f, 0.005228722468018532f, 0.0032351932022720575f, 0.004227771889418364f, 0.004256702493876219f, 0.003436743514612317f, 0.0055870171636343f, 0.005751708522439003f, 0.004252978600561619f, 0.006768917664885521f, 0.00594013836234808f, 0.003703727386891842f, 0.0028010853566229343f, 0.005230769980698824f, 0.00434520747512579f, 0.0033229507971554995f, 0.0022018684539943933f, 0.0031512537971138954f, 0.004425013903528452f, 0.0031325442250818014f, 0.0029210811480879784f, 0.004779856652021408f, 0.003384828567504883f, 0.005174637772142887f, 0.006999581586569548f, 0.004028548486530781f, 0.004540275316685438f, 0.004395405296236277f, 0.0034411584492772818f, 0.003183136461302638f, 0.003772478550672531f, 0.0029523123521357775f, 0.00657315319404006f, 0.003309521358460188f, 0.0032680376898497343f, 0.004744485951960087f, 0.0037425656337291002f, 0.003728443756699562f, 0.0033349187579005957f, 0.0049038901925086975f, 0.006123861763626337f, 0.004762924276292324f, 0.0041076987981796265f, 0.003906832542270422f, 0.004557866603136063f, 0.004267956130206585f, 0.004819660913199186f, 0.004263854585587978f, 0.004107381217181683f, 0.010517779737710953f, 0.004218589048832655f, 0.004827613942325115f, 0.004730855580419302f, 0.0025991364382207394f, 0.006264200899749994f, 0.004621963016688824f, 0.0036842527333647013f, 0.004041928797960281f, 0.005446570925414562f, 0.005041175987571478f, 0.003012227127328515f, 0.006616488099098206f, 0.004038445185869932f, 0.005760840140283108f, 0.0031199222430586815f, 0.00426489720121026f, 0.005478603299707174f, 0.005365799181163311f, 0.003917432855814695f, 0.003691386664286256f, 0.003494436852633953f, 0.004042632412165403f, 0.003858396550640464f, 0.00605932530015707f, 0.004177749156951904f, 0.003961083944886923f, 0.003417997620999813f, 0.003088592551648617f, 0.006028438452631235f, 0.005504872649908066f, 0.0028400993905961514f, 0.0039914315566420555f, 0.0033416289370507f, 0.007695183157920837f, 0.005369085818529129f, 0.002522702096030116f, 0.006730083841830492f, 0.003973614424467087f, 0.0034177524503320456f, 0.005535871256142855f, 0.003967760130763054f, 0.0038398460019379854f, 0.0037295962683856487f, 0.0030792776960879564f, 0.004769270773977041f, 0.0031943926587700844f, 0.004551413469016552f, 0.004963331390172243f, 0.004342022817581892f, 0.003915519919246435f, 0.0036346593406051397f, 0.004830393474549055f, 0.003426732262596488f, 0.004806129727512598f, 0.0040207174606621265f, 0.0057437908835709095f, 0.005388753022998571f, 0.00444916682317853f, 0.006650177761912346f, 0.0037141195498406887f, 0.004762967582792044f, 0.004468377213925123f, 0.004401376936584711f, 0.004047466441988945f, 0.003902002004906535f, 0.002676380332559347f, 0.004703028593212366f, 0.002371236216276884f, 0.005621899850666523f, 0.005959723610430956f, 0.00355141912586987f, 0.0036710991989821196f, 0.003606990445405245f, 0.003159488318488002f, 0.003590464126318693f, 0.003398060565814376f, 0.0033835407812148333f, 0.005188658367842436f, 0.0032415103632956743f, 0.00403841957449913f, 0.00837219599634409f, 0.004278877284377813f, 0.009572843089699745f, 0.0057801720686256886f, 0.006027944386005402f, 0.002294933656230569f, 0.004717292729765177f, 0.004210606683045626f, 0.004758625291287899f, 0.005201737396419048f, 0.004222861025482416f, 0.004339069593697786f, 0.005094386637210846f, 0.0037945248186588287f, 0.004123045597225428f, 0.003725695190951228f, 0.0030750338919460773f, 0.004963809624314308f, 0.0026054303161799908f, 0.0057108234614133835f, 0.0037869098596274853f, 0.003939366899430752f, 0.004976623225957155f, 0.0040126037783920765f, 0.004667759872972965f, 0.004492546897381544f, 0.0035866759717464447f, 0.005327802151441574f, 0.004482387099415064f, 0.005602497141808271f, 0.006597551517188549f, 0.004847484640777111f, 0.004723071586340666f, 0.0052331676706671715f, 0.005432622507214546f, 0.003280651057139039f, 0.004336026031523943f, 0.004359120968729258f, 0.00442127650603652f, 0.003738914616405964f, 0.004116381984204054f, 0.0035154088400304317f, 0.004799258429557085f, 0.004435059614479542f, 0.004218829330056906f, 0.003191908122971654f, 0.005143546033650637f, 0.0035934175830334425f, 0.004580663051456213f, 0.0033636968582868576f, 0.005157129373401403f, 0.0055895219556987286f, 0.002924465574324131f, 0.005479975137859583f, 0.0034131428692489862f, 0.00537830451503396f, 0.003650219179689884f, 0.003946911543607712f, 0.005622098222374916f, 0.010028036311268806f, 0.004471659194678068f);
static const ai_layer_format_type conv2d_26_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_LAST_VALID;

static const ai_i8 conv2d_27_pad_before_v_pad_constant_value_const_s8[] = LITE_ARRAY_VALUES(-128);
static const ai_i16 conv2d_27_pad_before_t_in_0_fmt_bitsize_const_s16 = 8;
static const ai_u32 conv2d_27_pad_before_t_in_0_shape_h_const_u32 = 3;

static const ai_u16 conv2d_27_t_in_0_shape_w_const_u16 = 5;
static const ai_u16 conv2d_27_t_in_0_shape_h_const_u16 = 5;
static const ai_u16 conv2d_27_t_in_0_shape_ch_const_u16 = 256;
static const ai_u16 conv2d_27_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_27_l_stride_0_const_u16 = 1;
static const ai_i8 conv2d_27_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_27_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_27_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_27_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_27_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.005957027431577444f, 0.008379107341170311f, 0.0023999602999538183f, 0.005626522470265627f, 0.005235164891928434f, 0.002874497091397643f, 0.01104776095598936f, 0.002639609621837735f, 0.0029849966522306204f, 0.002169863088056445f, 0.0025427916552871466f, 0.003574901958927512f, 0.002732607303187251f, 0.0028177439235150814f, 0.0031471557449549437f, 0.002968501066789031f, 0.004379099700599909f, 0.005013969261199236f, 0.0024461231660097837f, 0.0029406787361949682f, 0.005671356804668903f, 0.002507544821128249f, 0.0033411087933927774f, 0.0022195230703800917f, 0.00966494157910347f, 0.012372510507702827f, 0.0030888868495821953f, 0.0033214259892702103f, 0.0046275765635073185f, 0.0023019618820399046f, 0.002501856070011854f, 0.0032935980707406998f, 0.004752333275973797f, 0.0030348035506904125f, 0.004639174323529005f, 0.00914541631937027f, 0.005430981051176786f, 0.0025517544709146023f, 0.002270229859277606f, 0.0025723252911120653f, 0.014872979372739792f, 0.004429180175065994f, 0.005178805440664291f, 0.0029813386499881744f, 0.006383114960044622f, 0.003043399192392826f, 0.009167433716356754f, 0.002150348387658596f, 0.002106639090925455f, 0.0017665114719420671f, 0.0060439324006438255f, 0.007095983251929283f, 0.0023318121675401926f, 0.004886995069682598f, 0.003065394936129451f, 0.002539203502237797f, 0.004945171996951103f, 0.005336421076208353f, 0.002902511740103364f, 0.0028432197868824005f, 0.002903854474425316f, 0.00212413864210248f, 0.0025551242288202047f, 0.008306482806801796f, 0.0035309449303895235f, 0.0064402190037071705f, 0.0029431027360260487f, 0.0032062388490885496f, 0.0029993595089763403f, 0.0031851993408054113f, 0.0030723088420927525f, 0.0030299050267785788f, 0.0025014355778694153f, 0.0030043148435652256f, 0.003315440844744444f, 0.0023728548549115658f, 0.009916429407894611f, 0.003493858966976404f, 0.002758291084319353f, 0.0053086658008396626f, 0.002750521758571267f, 0.014915050007402897f, 0.0028755899984389544f, 0.002970110857859254f, 0.005245288368314505f, 0.0043721492402255535f, 0.002606283873319626f, 0.002701010089367628f, 0.0022817098069936037f, 0.002222180599346757f, 0.006241174414753914f, 0.0027916114777326584f, 0.0030912074726074934f, 0.003623829921707511f, 0.004540337715297937f, 0.0034750928170979023f, 0.002285497263073921f, 0.007021377794444561f, 0.004375595133751631f, 0.005908285267651081f, 0.0034287588205188513f, 0.002812781371176243f, 0.002489593578502536f, 0.0028156703338027f, 0.003172132885083556f, 0.002983556594699621f, 0.002617701655253768f, 0.0026623059529811144f, 0.003185500390827656f, 0.002795194508507848f, 0.003272783011198044f, 0.006810142658650875f, 0.005315456073731184f, 0.0036651520058512688f, 0.0021682055667042732f, 0.0028472370468080044f, 0.003491800744086504f, 0.004485382232815027f, 0.008110138587653637f, 0.004980045836418867f, 0.0023901876993477345f, 0.003476593177765608f, 0.0028548259288072586f, 0.0029993827920407057f, 0.004290513228625059f, 0.003187652910128236f, 0.002071161288768053f, 0.002362592378631234f, 0.01949366368353367f, 0.003460115985944867f, 0.002596356440335512f, 0.0037513209972530603f, 0.004604107700288296f, 0.0029529398307204247f, 0.0059757777489721775f, 0.004230701830238104f, 0.010489878244698048f, 0.002834731014445424f, 0.004067509900778532f, 0.003587174229323864f, 0.003799250116571784f, 0.0028038884047418833f, 0.0050788940861821175f, 0.00224673910997808f, 0.005466329865157604f, 0.0032526941504329443f, 0.007659418508410454f, 0.0030894866213202477f, 0.0020874692127108574f, 0.002705647610127926f, 0.00930487085133791f, 0.0023383416701108217f, 0.00528511218726635f, 0.00447833351790905f, 0.0020938680972903967f, 0.0025421874597668648f, 0.002448413521051407f, 0.0032188270706683397f, 0.0029218881390988827f, 0.010051979683339596f, 0.004200371447950602f, 0.006426218431442976f, 0.002761690178886056f, 0.002980121411383152f, 0.004593162331730127f, 0.00234772777184844f, 0.0028337363619357347f, 0.002688080072402954f, 0.0026283548213541508f, 0.00435854634270072f, 0.0027147543150931597f, 0.0029116894584149122f, 0.008003816939890385f, 0.0028457220178097486f, 0.002786006312817335f, 0.004992182366549969f, 0.002213078085333109f, 0.005017881281673908f, 0.003346435260027647f, 0.0028776538092643023f, 0.018693791702389717f, 0.002628022339195013f, 0.0035642539151012897f, 0.002247883938252926f, 0.0049403696320950985f, 0.003190622664988041f, 0.002498242538422346f, 0.002765604527667165f, 0.02035341039299965f, 0.0124513553455472f, 0.007368177641183138f, 0.0028124037198722363f, 0.0026032947935163975f, 0.003974003717303276f, 0.005032023414969444f, 0.003915606066584587f, 0.0027574447449296713f, 0.021946275606751442f, 0.01539530698210001f, 0.009445641189813614f, 0.014552240259945393f, 0.005155033431947231f, 0.004651608876883984f, 0.003100631758570671f, 0.002083890838548541f, 0.0030672794673591852f, 0.0028059089090675116f, 0.003606810001656413f, 0.0020368078257888556f, 0.0025987199041992426f, 0.005096693057566881f, 0.00249015842564404f, 0.0034831855446100235f, 0.01076957955956459f, 0.00207821698859334f, 0.002209786558523774f, 0.0024588764645159245f, 0.004078910686075687f, 0.003103019902482629f, 0.002763172844424844f, 0.0018717208877205849f, 0.0027682199142873287f, 0.0019856789149343967f, 0.0033125863410532475f, 0.002312573604285717f, 0.008853445760905743f, 0.0022117949556559324f, 0.002530583878979087f, 0.008515655063092709f, 0.0042671444825828075f, 0.004064767621457577f, 0.0025712510105222464f, 0.011227516457438469f, 0.014582871459424496f, 0.003309085266664624f, 0.0025830662343651056f, 0.012837548740208149f, 0.0024407804012298584f, 0.0028652269393205643f, 0.005771897733211517f, 0.0027943062596023083f, 0.012233665212988853f, 0.012532886117696762f, 0.013881970196962357f, 0.004115869291126728f, 0.003242029808461666f, 0.002253563143312931f, 0.0034717421513050795f, 0.005988785997033119f, 0.003892946755513549f, 0.003166120033711195f, 0.0030803971458226442f, 0.003296400886029005f, 0.0033019008114933968f, 0.02838023006916046f, 0.003319909330457449f);
static const ai_u16 conv2d_27_t_out_0_shape_w_const_u16 = 3;
static const ai_u16 conv2d_27_t_out_0_shape_h_const_u16 = 3;

static const ai_u16 conv2d_28_t_in_0_shape_w_const_u16 = 3;
static const ai_u16 conv2d_28_t_in_0_shape_h_const_u16 = 3;
static const ai_u16 conv2d_28_l_stride_1_const_u16 = 1;
static const ai_u16 conv2d_28_l_stride_0_const_u16 = 1;
static const ai_u16 conv2d_28_t_in_0_shape_ch_const_u16 = 256;
static const ai_u16 conv2d_28_t_out_0_shape_ch_const_u16 = 256;
static const ai_i8 conv2d_28_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 conv2d_28_t_out_0_fmt_zero_const_s8 = -128;
static const ai_float conv2d_28_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_28_t_out_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float conv2d_28_t_weight_0_fmt_scale_const_f32[] = LITE_ARRAY_VALUES(0.01380922831594944f, 0.017325809225440025f, 0.016414526849985123f, 0.013780943118035793f, 0.021761121228337288f, 0.012681316584348679f, 0.016552846878767014f, 0.028319181874394417f, 0.017606375738978386f, 0.015570351853966713f, 0.01383592002093792f, 0.018383188173174858f, 0.014405135996639729f, 0.016324728727340698f, 0.017448684200644493f, 0.014513669535517693f, 0.01400654949247837f, 0.015802469104528427f, 0.01907338760793209f, 0.018589511513710022f, 0.013413755223155022f, 0.011867361143231392f, 0.014480558224022388f, 0.014314699918031693f, 0.013659007847309113f, 0.034992069005966187f, 0.012174263596534729f, 0.011709455400705338f, 0.012433118186891079f, 0.02282874658703804f, 0.013058287091553211f, 0.015987928956747055f, 0.01664305105805397f, 0.012294861488044262f, 0.014453406445682049f, 0.018029827624559402f, 0.013045351952314377f, 0.013817946426570415f, 0.015368020161986351f, 0.014963923953473568f, 0.012852417305111885f, 0.017442500218749046f, 0.015447864308953285f, 0.014483178965747356f, 0.015248673968017101f, 0.018314506858587265f, 0.014094632118940353f, 0.015515940263867378f, 0.014529259875416756f, 0.01609603688120842f, 0.019022854045033455f, 0.04482223093509674f, 0.014798137359321117f, 0.015543146058917046f, 0.019568350166082382f, 0.02131265215575695f, 0.013466263189911842f, 0.01820313185453415f, 0.017346348613500595f, 0.017755763605237007f, 0.014809009619057178f, 0.014428244903683662f, 0.016634127125144005f, 0.015800023451447487f, 0.015515949577093124f, 0.017282864078879356f, 0.01586037687957287f, 0.012278147041797638f, 0.02113593928515911f, 0.01905341073870659f, 0.013355443254113197f, 0.01373339258134365f, 0.017417721450328827f, 0.02019849792122841f, 0.01454775221645832f, 0.01724908873438835f, 0.010808481834828854f, 0.018824394792318344f, 0.01940109394490719f, 0.014046650379896164f, 0.018094351515173912f, 0.02407241426408291f, 0.015188188292086124f, 0.024715662002563477f, 0.015540177933871746f, 0.011750297620892525f, 0.018713995814323425f, 0.014298051595687866f, 0.01383946929126978f, 0.02047990821301937f, 0.022367872297763824f, 0.016496820375323296f, 0.0146249420940876f, 0.02555018663406372f, 0.0207024198025465f, 0.011918670497834682f, 0.013401522301137447f, 0.01464372593909502f, 0.01373985130339861f, 0.017156850546598434f, 0.011668441817164421f, 0.013758496381342411f, 0.013583102263510227f, 0.012532859109342098f, 0.016694286838173866f, 0.013239055871963501f, 0.015781907364726067f, 0.015658533200621605f, 0.013817021623253822f, 0.014088914729654789f, 0.018019529059529305f, 0.016487551853060722f, 0.015466590411961079f, 0.02083861082792282f, 0.014566165395081043f, 0.022793415933847427f, 0.0129546532407403f, 0.018025068566203117f, 0.013071735389530659f, 0.012767637148499489f, 0.014140009880065918f, 0.017374934628605843f, 0.01745459996163845f, 0.017025427892804146f, 0.01994616724550724f, 0.01429736241698265f, 0.01735914871096611f, 0.05211948603391647f, 0.01643861085176468f, 0.01942499727010727f, 0.020960047841072083f, 0.01828974299132824f, 0.020001128315925598f, 0.03976425155997276f, 0.016552025452256203f, 0.02532992698252201f, 0.013810700736939907f, 0.015490731224417686f, 0.06772073358297348f, 0.016210459172725677f, 0.012467129155993462f, 0.015995332971215248f, 0.013850096613168716f, 0.015731703490018845f, 0.01487540453672409f, 0.010843290016055107f, 0.01702447049319744f, 0.014614619314670563f, 0.019138874486088753f, 0.0134392399340868f, 0.016003331169486046f, 0.013864097185432911f, 0.023292697966098785f, 0.013466700911521912f, 0.01330434437841177f, 0.015782702714204788f, 0.013043043203651905f, 0.027456462383270264f, 0.011526849120855331f, 0.015053695067763329f, 0.01586022414267063f, 0.015521248802542686f, 0.013710252940654755f, 0.015698084607720375f, 0.011190288700163364f, 0.015825878828763962f, 0.013610338792204857f, 0.01797989010810852f, 0.013108925893902779f, 0.017384741455316544f, 0.01564965583384037f, 0.014541064389050007f, 0.01675623655319214f, 0.017189081758260727f, 0.01554984599351883f, 0.018291840329766273f, 0.020404953509569168f, 0.013800528831779957f, 0.01575400121510029f, 0.017417699098587036f, 0.014308120124042034f, 0.013391864486038685f, 0.01896662451326847f, 0.013697882182896137f, 0.01571357622742653f, 0.017409810796380043f, 0.018406692892313004f, 0.02969534508883953f, 0.01603921875357628f, 0.023291010409593582f, 0.012539852410554886f, 0.014856575056910515f, 0.01359530445188284f, 0.015153213404119015f, 0.01148967631161213f, 0.015431965701282024f, 0.015707412734627724f, 0.016058018431067467f, 0.018372835591435432f, 0.018872329965233803f, 0.015419531613588333f, 0.01448651123791933f, 0.012105914764106274f, 0.013299526646733284f, 0.012148863635957241f, 0.020478609949350357f, 0.012349308468401432f, 0.011006224900484085f, 0.017570091411471367f, 0.013704412616789341f, 0.017377225682139397f, 0.01519800629466772f, 0.016022436320781708f, 0.018356716260313988f, 0.013966714031994343f, 0.01194434892386198f, 0.015593917109072208f, 0.022031787782907486f, 0.011703472584486008f, 0.015295245684683323f, 0.01423237007111311f, 0.01369540300220251f, 0.015277964062988758f, 0.012341621331870556f, 0.016750745475292206f, 0.017311103641986847f, 0.014744837768375874f, 0.017909076064825058f, 0.024169474840164185f, 0.019020918756723404f, 0.012445208616554737f, 0.015556976199150085f, 0.019358688965439796f, 0.035157814621925354f, 0.01801171712577343f, 0.016068292781710625f, 0.018399149179458618f, 0.01645159162580967f, 0.016002988442778587f, 0.01210588775575161f, 0.014452481642365456f, 0.01236460916697979f, 0.017233170568943024f, 0.011371106840670109f, 0.01228153333067894f, 0.0192821454256773f, 0.013562965206801891f, 0.023034313693642616f, 0.013270444236695766f, 0.019371218979358673f, 0.01913166418671608f, 0.01451475266367197f, 0.018304578959941864f, 0.013676516711711884f, 0.015141915529966354f, 0.015683071687817574f);
static const ai_layer_format_type conv2d_28_l_out_ch_format_const_layer_format_type = AI_LAYER_FORMAT_CHANNEL_LAST_VALID;


static const ai_i8 gemm_30_t_in_0_fmt_zero_const_s8 = -128;
static const ai_i8 gemm_30_t_out_0_fmt_zero_const_s8 = -31;
static const ai_u16 gemm_30_t_in_0_shape_ch_const_u16 = 256;
static const ai_u16 gemm_30_t_out_0_shape_ch_const_u16 = 6;
static const ai_u32 gemm_30_t_out_0_shape_h_w_prod_const_u32 = 1;
static const ai_float gemm_30_t_in_0_fmt_scale_const_f32 = 0.0235294122248888f;
static const ai_float gemm_30_t_out_0_fmt_scale_const_f32 = 0.09457084536552429f;
static const ai_float gemm_30_t_weight_0_fmt_scale_const_f32 = 0.0029600828420370817f;
STAI_API_ENTRY
stai_return_code stai_gs_network_run(
  stai_network* network,
  const stai_run_mode mode)
{
   STAI_UNUSED(mode)
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)

  _STAI_SET_ERROR(net_ctx, (net_ctx->_flags & STAI_FLAG_ACTIVATIONS) != STAI_FLAG_ACTIVATIONS,
        STAI_ERROR_NETWORK_INVALID_ACTIVATIONS_PTR, net_ctx->_return_code)

  _STAI_SET_ERROR(net_ctx, (net_ctx->_flags & STAI_FLAG_INPUTS) != STAI_FLAG_INPUTS,
                  STAI_ERROR_NETWORK_INVALID_IN_PTR, net_ctx->_return_code)
  _STAI_SET_ERROR(net_ctx, (net_ctx->_flags & STAI_FLAG_OUTPUTS) != STAI_FLAG_OUTPUTS,
                  STAI_ERROR_NETWORK_INVALID_OUT_PTR, net_ctx->_return_code)

  _STAI_SET_ERROR(net_ctx, (net_ctx->_flags & STAI_FLAG_WEIGHTS) != STAI_FLAG_WEIGHTS,
                  STAI_ERROR_NETWORK_INVALID_WEIGHTS_PTR, net_ctx->_return_code)


  /* LITE_KERNEL_SECTION BEGIN eltwise_0 */
  {
    
  forward_lite_eltwise_integer_INT8_eltwise_0(net_ctx);
  }
  /* LITE_KERNEL_SECTION END eltwise_0 */
  /* LITE_KERNEL_SECTION BEGIN eltwise_1 */
  {
    
  forward_lite_eltwise_integer_INT8_eltwise_1(net_ctx);
  }
  /* LITE_KERNEL_SECTION END eltwise_1 */
  /* LITE_KERNEL_SECTION BEGIN conv2d_2 */
  {
      const ai_i8* conv2d_2_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 192);
    const ai_i8* conv2d_2_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 8);
    const ai_i32* conv2d_2_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 224);
    ai_i8* conv2d_2_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 27844);
    ai_i16* conv2d_2_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 54840);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(2, 1, {(stai_ptr) conv2d_2_t_in_0_ptr_const_s8});
    
  forward_lite_conv2d_rgb_sssa8_ch(conv2d_2_t_in_0_ptr_const_s8, conv2d_2_t_in_0_shape_w_const_u16, conv2d_2_t_weight_0_ptr_const_s8, conv2d_2_t_out_0_shape_ch_const_u16, conv2d_2_t_weight_0_shape_w_const_u16, conv2d_2_l_pad_W_0_const_s32, conv2d_2_l_stride_0_const_u16, conv2d_2_t_weight_1_ptr_const_s32, conv2d_2_t_in_0_fmt_zero_const_s8, conv2d_2_t_out_0_fmt_zero_const_s8, conv2d_2_t_in_0_fmt_scale_const_f32, conv2d_2_t_out_0_fmt_scale_const_f32, conv2d_2_t_weight_0_fmt_scale_const_f32, conv2d_2_l_out_ch_format_const_layer_format_type, conv2d_2_t_out_0_ptr_s8, conv2d_2_t_out_0_shape_w_const_u16, 652, conv2d_2_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(2, 1, {(stai_ptr) conv2d_2_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_2 */
  if (!gs_cubeai_layer_done(0U, 18432U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_3_pad_before */
  {
    
  forward_lite_pad_conv2d_3_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_3_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_3 */
  {
      const ai_i8* conv2d_3_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 27844);
    const ai_i8* conv2d_3_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 256);
    const ai_i32* conv2d_3_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 328);
    ai_i8* conv2d_3_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 192);
    ai_i16* conv2d_3_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 47844);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(3, 1, {(stai_ptr) conv2d_3_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_3_t_in_0_ptr_const_s8, conv2d_3_t_in_0_shape_w_const_u16, conv2d_3_t_in_0_shape_h_const_u16, conv2d_3_t_in_0_shape_ch_const_u16, conv2d_3_t_weight_0_ptr_const_s8, conv2d_3_l_stride_1_const_u16, conv2d_3_l_stride_0_const_u16, conv2d_3_t_weight_1_ptr_const_s32, conv2d_3_t_in_0_fmt_zero_const_s8, conv2d_3_t_out_0_fmt_zero_const_s8, conv2d_3_t_in_0_fmt_scale_const_f32, conv2d_3_t_out_0_fmt_scale_const_f32, conv2d_3_t_weight_0_fmt_scale_const_f32, conv2d_3_t_out_0_ptr_s8, conv2d_3_t_out_0_shape_w_const_u16, conv2d_3_t_out_0_shape_h_const_u16, 0, 272, conv2d_3_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(3, 1, {(stai_ptr) conv2d_3_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_3 */
  if (!gs_cubeai_layer_done(1U, 18432U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_4 */
  {
      const ai_i8* conv2d_4_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 192);
    const ai_i8* conv2d_4_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 360);
    const ai_i32* conv2d_4_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 488);
    ai_i8* conv2d_4_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 18624);
    ai_i16* conv2d_4_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(4, 1, {(stai_ptr) conv2d_4_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_4_t_in_0_ptr_const_s8, conv2d_4_t_in_0_shape_w_const_u16, conv2d_4_t_in_0_shape_h_const_u16, conv2d_4_l_stride_1_const_u16, conv2d_4_l_stride_0_const_u16, conv2d_4_t_in_0_shape_ch_const_u16, conv2d_4_t_weight_0_ptr_const_s8, conv2d_4_t_out_0_shape_ch_const_u16, conv2d_4_t_weight_1_ptr_const_s32, conv2d_4_t_in_0_fmt_zero_const_s8, conv2d_4_t_out_0_fmt_zero_const_s8, conv2d_4_t_in_0_fmt_scale_const_f32, conv2d_4_t_out_0_fmt_scale_const_f32, conv2d_4_t_weight_0_fmt_scale_const_f32, conv2d_4_l_out_ch_format_const_layer_format_type, conv2d_4_t_out_0_ptr_s8, 1, 192, conv2d_4_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(4, 1, {(stai_ptr) conv2d_4_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_4 */
  if (!gs_cubeai_layer_done(2U, 36864U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_5_pad_before */
  {
    
  forward_lite_pad_conv2d_5_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_5_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_5 */
  {
      const ai_i8* conv2d_5_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 18624);
    const ai_i8* conv2d_5_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 552);
    const ai_i32* conv2d_5_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 696);
    ai_i8* conv2d_5_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 544);
    ai_i16* conv2d_5_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(5, 1, {(stai_ptr) conv2d_5_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_5_t_in_0_ptr_const_s8, conv2d_5_t_in_0_shape_w_const_u16, conv2d_5_t_in_0_shape_h_const_u16, conv2d_5_t_in_0_shape_ch_const_u16, conv2d_5_t_weight_0_ptr_const_s8, conv2d_5_l_stride_1_const_u16, conv2d_5_l_stride_0_const_u16, conv2d_5_t_weight_1_ptr_const_s32, conv2d_5_t_in_0_fmt_zero_const_s8, conv2d_5_t_out_0_fmt_zero_const_s8, conv2d_5_t_in_0_fmt_scale_const_f32, conv2d_5_t_out_0_fmt_scale_const_f32, conv2d_5_t_weight_0_fmt_scale_const_f32, conv2d_5_t_out_0_ptr_s8, conv2d_5_t_out_0_shape_w_const_u16, conv2d_5_t_out_0_shape_h_const_u16, 0, 544, conv2d_5_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(5, 1, {(stai_ptr) conv2d_5_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_5 */
  if (!gs_cubeai_layer_done(3U, 9216U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_6 */
  {
      const ai_i8* conv2d_6_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 544);
    const ai_i8* conv2d_6_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 760);
    const ai_i32* conv2d_6_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 1272);
    ai_i8* conv2d_6_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 9760);
    ai_i16* conv2d_6_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(6, 1, {(stai_ptr) conv2d_6_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_6_t_in_0_ptr_const_s8, conv2d_6_t_in_0_shape_w_const_u16, conv2d_6_t_in_0_shape_h_const_u16, conv2d_6_l_stride_1_const_u16, conv2d_6_l_stride_0_const_u16, conv2d_6_t_in_0_shape_ch_const_u16, conv2d_6_t_weight_0_ptr_const_s8, conv2d_6_t_out_0_shape_ch_const_u16, conv2d_6_t_weight_1_ptr_const_s32, conv2d_6_t_in_0_fmt_zero_const_s8, conv2d_6_t_out_0_fmt_zero_const_s8, conv2d_6_t_in_0_fmt_scale_const_f32, conv2d_6_t_out_0_fmt_scale_const_f32, conv2d_6_t_weight_0_fmt_scale_const_f32, conv2d_6_l_out_ch_format_const_layer_format_type, conv2d_6_t_out_0_ptr_s8, 1, 384, conv2d_6_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(6, 1, {(stai_ptr) conv2d_6_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_6 */
  if (!gs_cubeai_layer_done(4U, 18432U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_7_pad_before */
  {
    
  forward_lite_pad_conv2d_7_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_7_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_7 */
  {
      const ai_i8* conv2d_7_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 9760);
    const ai_i8* conv2d_7_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 1400);
    const ai_i32* conv2d_7_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 1688);
    ai_i8* conv2d_7_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 31392);
    ai_i16* conv2d_7_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(7, 1, {(stai_ptr) conv2d_7_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_7_t_in_0_ptr_const_s8, conv2d_7_t_in_0_shape_w_const_u16, conv2d_7_t_in_0_shape_h_const_u16, conv2d_7_t_in_0_shape_ch_const_u16, conv2d_7_t_weight_0_ptr_const_s8, conv2d_7_l_stride_1_const_u16, conv2d_7_l_stride_0_const_u16, conv2d_7_t_weight_1_ptr_const_s32, conv2d_7_t_in_0_fmt_zero_const_s8, conv2d_7_t_out_0_fmt_zero_const_s8, conv2d_7_t_in_0_fmt_scale_const_f32, conv2d_7_t_out_0_fmt_scale_const_f32, conv2d_7_t_weight_0_fmt_scale_const_f32, conv2d_7_t_out_0_ptr_s8, conv2d_7_t_out_0_shape_w_const_u16, conv2d_7_t_out_0_shape_h_const_u16, 0, 1088, conv2d_7_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(7, 1, {(stai_ptr) conv2d_7_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_7 */
  if (!gs_cubeai_layer_done(5U, 18432U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_8 */
  {
      const ai_i8* conv2d_8_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 31392);
    const ai_i8* conv2d_8_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 1816);
    const ai_i32* conv2d_8_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 2840);
    ai_i8* conv2d_8_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 448);
    ai_i16* conv2d_8_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(8, 1, {(stai_ptr) conv2d_8_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_8_t_in_0_ptr_const_s8, conv2d_8_t_in_0_shape_w_const_u16, conv2d_8_t_in_0_shape_h_const_u16, conv2d_8_l_stride_1_const_u16, conv2d_8_l_stride_0_const_u16, conv2d_8_t_in_0_shape_ch_const_u16, conv2d_8_t_weight_0_ptr_const_s8, conv2d_8_t_out_0_shape_ch_const_u16, conv2d_8_t_weight_1_ptr_const_s32, conv2d_8_t_in_0_fmt_zero_const_s8, conv2d_8_t_out_0_fmt_zero_const_s8, conv2d_8_t_in_0_fmt_scale_const_f32, conv2d_8_t_out_0_fmt_scale_const_f32, conv2d_8_t_weight_0_fmt_scale_const_f32, conv2d_8_l_out_ch_format_const_layer_format_type, conv2d_8_t_out_0_ptr_s8, 1, 448, conv2d_8_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(8, 1, {(stai_ptr) conv2d_8_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_8 */
  if (!gs_cubeai_layer_done(6U, 18432U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_9_pad_before */
  {
    
  forward_lite_pad_conv2d_9_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_9_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_9 */
  {
      const ai_i8* conv2d_9_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 448);
    const ai_i8* conv2d_9_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 2968);
    const ai_i32* conv2d_9_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 3256);
    ai_i8* conv2d_9_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 23168);
    ai_i16* conv2d_9_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 22080);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(9, 1, {(stai_ptr) conv2d_9_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_9_t_in_0_ptr_const_s8, conv2d_9_t_in_0_shape_w_const_u16, conv2d_9_t_in_0_shape_h_const_u16, conv2d_9_t_in_0_shape_ch_const_u16, conv2d_9_t_weight_0_ptr_const_s8, conv2d_9_l_stride_1_const_u16, conv2d_9_l_stride_0_const_u16, conv2d_9_t_weight_1_ptr_const_s32, conv2d_9_t_in_0_fmt_zero_const_s8, conv2d_9_t_out_0_fmt_zero_const_s8, conv2d_9_t_in_0_fmt_scale_const_f32, conv2d_9_t_out_0_fmt_scale_const_f32, conv2d_9_t_weight_0_fmt_scale_const_f32, conv2d_9_t_out_0_ptr_s8, conv2d_9_t_out_0_shape_w_const_u16, conv2d_9_t_out_0_shape_h_const_u16, 0, 1088, conv2d_9_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(9, 1, {(stai_ptr) conv2d_9_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_9 */
  if (!gs_cubeai_layer_done(7U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_10 */
  {
      const ai_i8* conv2d_10_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 23168);
    const ai_i8* conv2d_10_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 3384);
    const ai_i32* conv2d_10_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 5432);
    ai_i8* conv2d_10_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 768);
    ai_i16* conv2d_10_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(10, 1, {(stai_ptr) conv2d_10_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_10_t_in_0_ptr_const_s8, conv2d_10_t_in_0_shape_w_const_u16, conv2d_10_t_in_0_shape_h_const_u16, conv2d_10_l_stride_1_const_u16, conv2d_10_l_stride_0_const_u16, conv2d_10_t_in_0_shape_ch_const_u16, conv2d_10_t_weight_0_ptr_const_s8, conv2d_10_t_out_0_shape_ch_const_u16, conv2d_10_t_weight_1_ptr_const_s32, conv2d_10_t_in_0_fmt_zero_const_s8, conv2d_10_t_out_0_fmt_zero_const_s8, conv2d_10_t_in_0_fmt_scale_const_f32, conv2d_10_t_out_0_fmt_scale_const_f32, conv2d_10_t_weight_0_fmt_scale_const_f32, conv2d_10_l_out_ch_format_const_layer_format_type, conv2d_10_t_out_0_ptr_s8, 1, 768, conv2d_10_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(10, 1, {(stai_ptr) conv2d_10_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_10 */
  if (!gs_cubeai_layer_done(8U, 9216U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_11_pad_before */
  {
    
  forward_lite_pad_conv2d_11_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_11_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_11 */
  {
      const ai_i8* conv2d_11_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 768);
    const ai_i8* conv2d_11_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 5688);
    const ai_i32* conv2d_11_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 6264);
    ai_i8* conv2d_11_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 15488);
    ai_i16* conv2d_11_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 13312);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(11, 1, {(stai_ptr) conv2d_11_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_11_t_in_0_ptr_const_s8, conv2d_11_t_in_0_shape_w_const_u16, conv2d_11_t_in_0_shape_h_const_u16, conv2d_11_t_in_0_shape_ch_const_u16, conv2d_11_t_weight_0_ptr_const_s8, conv2d_11_l_stride_1_const_u16, conv2d_11_l_stride_0_const_u16, conv2d_11_t_weight_1_ptr_const_s32, conv2d_11_t_in_0_fmt_zero_const_s8, conv2d_11_t_out_0_fmt_zero_const_s8, conv2d_11_t_in_0_fmt_scale_const_f32, conv2d_11_t_out_0_fmt_scale_const_f32, conv2d_11_t_weight_0_fmt_scale_const_f32, conv2d_11_t_out_0_ptr_s8, conv2d_11_t_out_0_shape_w_const_u16, conv2d_11_t_out_0_shape_h_const_u16, 0, 2176, conv2d_11_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(11, 1, {(stai_ptr) conv2d_11_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_11 */
  if (!gs_cubeai_layer_done(9U, 9216U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_12 */
  {
      const ai_i8* conv2d_12_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 15488);
    const ai_i8* conv2d_12_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 6520);
    const ai_i32* conv2d_12_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 10616);
    ai_i8* conv2d_12_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 896);
    ai_i16* conv2d_12_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(12, 1, {(stai_ptr) conv2d_12_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_12_t_in_0_ptr_const_s8, conv2d_12_t_in_0_shape_w_const_u16, conv2d_12_t_in_0_shape_h_const_u16, conv2d_12_l_stride_1_const_u16, conv2d_12_l_stride_0_const_u16, conv2d_12_t_in_0_shape_ch_const_u16, conv2d_12_t_weight_0_ptr_const_s8, conv2d_12_t_out_0_shape_ch_const_u16, conv2d_12_t_weight_1_ptr_const_s32, conv2d_12_t_in_0_fmt_zero_const_s8, conv2d_12_t_out_0_fmt_zero_const_s8, conv2d_12_t_in_0_fmt_scale_const_f32, conv2d_12_t_out_0_fmt_scale_const_f32, conv2d_12_t_weight_0_fmt_scale_const_f32, conv2d_12_l_out_ch_format_const_layer_format_type, conv2d_12_t_out_0_ptr_s8, 1, 896, conv2d_12_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(12, 1, {(stai_ptr) conv2d_12_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_12 */
  if (!gs_cubeai_layer_done(10U, 9216U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_13_pad_before */
  {
    
  forward_lite_pad_conv2d_13_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_13_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_13 */
  {
      const ai_i8* conv2d_13_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 896);
    const ai_i8* conv2d_13_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 10872);
    const ai_i32* conv2d_13_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 11448);
    ai_i8* conv2d_13_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 15616);
    ai_i16* conv2d_13_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 13440);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(13, 1, {(stai_ptr) conv2d_13_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_13_t_in_0_ptr_const_s8, conv2d_13_t_in_0_shape_w_const_u16, conv2d_13_t_in_0_shape_h_const_u16, conv2d_13_t_in_0_shape_ch_const_u16, conv2d_13_t_weight_0_ptr_const_s8, conv2d_13_l_stride_1_const_u16, conv2d_13_l_stride_0_const_u16, conv2d_13_t_weight_1_ptr_const_s32, conv2d_13_t_in_0_fmt_zero_const_s8, conv2d_13_t_out_0_fmt_zero_const_s8, conv2d_13_t_in_0_fmt_scale_const_f32, conv2d_13_t_out_0_fmt_scale_const_f32, conv2d_13_t_weight_0_fmt_scale_const_f32, conv2d_13_t_out_0_ptr_s8, conv2d_13_t_out_0_shape_w_const_u16, conv2d_13_t_out_0_shape_h_const_u16, 0, 2176, conv2d_13_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(13, 1, {(stai_ptr) conv2d_13_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_13 */
  if (!gs_cubeai_layer_done(11U, 2304U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_14 */
  {
      const ai_i8* conv2d_14_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 15616);
    const ai_i8* conv2d_14_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 11704);
    const ai_i32* conv2d_14_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 19896);
    ai_i8* conv2d_14_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 1536);
    ai_i16* conv2d_14_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(14, 1, {(stai_ptr) conv2d_14_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_14_t_in_0_ptr_const_s8, conv2d_14_t_in_0_shape_w_const_u16, conv2d_14_t_in_0_shape_h_const_u16, conv2d_14_l_stride_1_const_u16, conv2d_14_l_stride_0_const_u16, conv2d_14_t_in_0_shape_ch_const_u16, conv2d_14_t_weight_0_ptr_const_s8, conv2d_14_t_out_0_shape_ch_const_u16, conv2d_14_t_weight_1_ptr_const_s32, conv2d_14_t_in_0_fmt_zero_const_s8, conv2d_14_t_out_0_fmt_zero_const_s8, conv2d_14_t_in_0_fmt_scale_const_f32, conv2d_14_t_out_0_fmt_scale_const_f32, conv2d_14_t_weight_0_fmt_scale_const_f32, conv2d_14_l_out_ch_format_const_layer_format_type, conv2d_14_t_out_0_ptr_s8, 1, 1536, conv2d_14_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(14, 1, {(stai_ptr) conv2d_14_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_14 */
  if (!gs_cubeai_layer_done(12U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_15_pad_before */
  {
    
  forward_lite_pad_conv2d_15_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_15_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_15 */
  {
      const ai_i8* conv2d_15_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 1536);
    const ai_i8* conv2d_15_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 20408);
    const ai_i32* conv2d_15_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 21560);
    ai_i8* conv2d_15_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 14080);
    ai_i16* conv2d_15_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 9728);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(15, 1, {(stai_ptr) conv2d_15_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_15_t_in_0_ptr_const_s8, conv2d_15_t_in_0_shape_w_const_u16, conv2d_15_t_in_0_shape_h_const_u16, conv2d_15_t_in_0_shape_ch_const_u16, conv2d_15_t_weight_0_ptr_const_s8, conv2d_15_l_stride_1_const_u16, conv2d_15_l_stride_0_const_u16, conv2d_15_t_weight_1_ptr_const_s32, conv2d_15_t_in_0_fmt_zero_const_s8, conv2d_15_t_out_0_fmt_zero_const_s8, conv2d_15_t_in_0_fmt_scale_const_f32, conv2d_15_t_out_0_fmt_scale_const_f32, conv2d_15_t_weight_0_fmt_scale_const_f32, conv2d_15_t_out_0_ptr_s8, conv2d_15_t_out_0_shape_w_const_u16, conv2d_15_t_out_0_shape_h_const_u16, 0, 4352, conv2d_15_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(15, 1, {(stai_ptr) conv2d_15_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_15 */
  if (!gs_cubeai_layer_done(13U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_16 */
  {
      const ai_i8* conv2d_16_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 14080);
    const ai_i8* conv2d_16_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 22072);
    const ai_i32* conv2d_16_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 38456);
    ai_i8* conv2d_16_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    ai_i16* conv2d_16_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(16, 1, {(stai_ptr) conv2d_16_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_16_t_in_0_ptr_const_s8, conv2d_16_t_in_0_shape_w_const_u16, conv2d_16_t_in_0_shape_h_const_u16, conv2d_16_l_stride_1_const_u16, conv2d_16_l_stride_0_const_u16, conv2d_16_t_in_0_shape_ch_const_u16, conv2d_16_t_weight_0_ptr_const_s8, conv2d_16_t_out_0_shape_ch_const_u16, conv2d_16_t_weight_1_ptr_const_s32, conv2d_16_t_in_0_fmt_zero_const_s8, conv2d_16_t_out_0_fmt_zero_const_s8, conv2d_16_t_in_0_fmt_scale_const_f32, conv2d_16_t_out_0_fmt_scale_const_f32, conv2d_16_t_weight_0_fmt_scale_const_f32, conv2d_16_l_out_ch_format_const_layer_format_type, conv2d_16_t_out_0_ptr_s8, 1, 1792, conv2d_16_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(16, 1, {(stai_ptr) conv2d_16_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_16 */
  if (!gs_cubeai_layer_done(14U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_17_pad_before */
  {
    
  forward_lite_pad_conv2d_17_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_17_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_17 */
  {
      const ai_i8* conv2d_17_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    const ai_i8* conv2d_17_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 38968);
    const ai_i32* conv2d_17_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 40120);
    ai_i8* conv2d_17_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 14336);
    ai_i16* conv2d_17_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 9984);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(17, 1, {(stai_ptr) conv2d_17_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_17_t_in_0_ptr_const_s8, conv2d_17_t_in_0_shape_w_const_u16, conv2d_17_t_in_0_shape_h_const_u16, conv2d_17_t_in_0_shape_ch_const_u16, conv2d_17_t_weight_0_ptr_const_s8, conv2d_17_l_stride_1_const_u16, conv2d_17_l_stride_0_const_u16, conv2d_17_t_weight_1_ptr_const_s32, conv2d_17_t_in_0_fmt_zero_const_s8, conv2d_17_t_out_0_fmt_zero_const_s8, conv2d_17_t_in_0_fmt_scale_const_f32, conv2d_17_t_out_0_fmt_scale_const_f32, conv2d_17_t_weight_0_fmt_scale_const_f32, conv2d_17_t_out_0_ptr_s8, conv2d_17_t_out_0_shape_w_const_u16, conv2d_17_t_out_0_shape_h_const_u16, 0, 4352, conv2d_17_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(17, 1, {(stai_ptr) conv2d_17_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_17 */
  if (!gs_cubeai_layer_done(15U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_18 */
  {
      const ai_i8* conv2d_18_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 14336);
    const ai_i8* conv2d_18_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 40632);
    const ai_i32* conv2d_18_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 57016);
    ai_i8* conv2d_18_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    ai_i16* conv2d_18_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(18, 1, {(stai_ptr) conv2d_18_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_18_t_in_0_ptr_const_s8, conv2d_18_t_in_0_shape_w_const_u16, conv2d_18_t_in_0_shape_h_const_u16, conv2d_18_l_stride_1_const_u16, conv2d_18_l_stride_0_const_u16, conv2d_18_t_in_0_shape_ch_const_u16, conv2d_18_t_weight_0_ptr_const_s8, conv2d_18_t_out_0_shape_ch_const_u16, conv2d_18_t_weight_1_ptr_const_s32, conv2d_18_t_in_0_fmt_zero_const_s8, conv2d_18_t_out_0_fmt_zero_const_s8, conv2d_18_t_in_0_fmt_scale_const_f32, conv2d_18_t_out_0_fmt_scale_const_f32, conv2d_18_t_weight_0_fmt_scale_const_f32, conv2d_18_l_out_ch_format_const_layer_format_type, conv2d_18_t_out_0_ptr_s8, 1, 1792, conv2d_18_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(18, 1, {(stai_ptr) conv2d_18_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_18 */
  if (!gs_cubeai_layer_done(16U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_19_pad_before */
  {
    
  forward_lite_pad_conv2d_19_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_19_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_19 */
  {
      const ai_i8* conv2d_19_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    const ai_i8* conv2d_19_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 57528);
    const ai_i32* conv2d_19_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 58680);
    ai_i8* conv2d_19_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 14336);
    ai_i16* conv2d_19_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 9984);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(19, 1, {(stai_ptr) conv2d_19_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_19_t_in_0_ptr_const_s8, conv2d_19_t_in_0_shape_w_const_u16, conv2d_19_t_in_0_shape_h_const_u16, conv2d_19_t_in_0_shape_ch_const_u16, conv2d_19_t_weight_0_ptr_const_s8, conv2d_19_l_stride_1_const_u16, conv2d_19_l_stride_0_const_u16, conv2d_19_t_weight_1_ptr_const_s32, conv2d_19_t_in_0_fmt_zero_const_s8, conv2d_19_t_out_0_fmt_zero_const_s8, conv2d_19_t_in_0_fmt_scale_const_f32, conv2d_19_t_out_0_fmt_scale_const_f32, conv2d_19_t_weight_0_fmt_scale_const_f32, conv2d_19_t_out_0_ptr_s8, conv2d_19_t_out_0_shape_w_const_u16, conv2d_19_t_out_0_shape_h_const_u16, 0, 4352, conv2d_19_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(19, 1, {(stai_ptr) conv2d_19_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_19 */
  if (!gs_cubeai_layer_done(17U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_20 */
  {
      const ai_i8* conv2d_20_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 14336);
    const ai_i8* conv2d_20_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 59192);
    const ai_i32* conv2d_20_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 75576);
    ai_i8* conv2d_20_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    ai_i16* conv2d_20_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(20, 1, {(stai_ptr) conv2d_20_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_20_t_in_0_ptr_const_s8, conv2d_20_t_in_0_shape_w_const_u16, conv2d_20_t_in_0_shape_h_const_u16, conv2d_20_l_stride_1_const_u16, conv2d_20_l_stride_0_const_u16, conv2d_20_t_in_0_shape_ch_const_u16, conv2d_20_t_weight_0_ptr_const_s8, conv2d_20_t_out_0_shape_ch_const_u16, conv2d_20_t_weight_1_ptr_const_s32, conv2d_20_t_in_0_fmt_zero_const_s8, conv2d_20_t_out_0_fmt_zero_const_s8, conv2d_20_t_in_0_fmt_scale_const_f32, conv2d_20_t_out_0_fmt_scale_const_f32, conv2d_20_t_weight_0_fmt_scale_const_f32, conv2d_20_l_out_ch_format_const_layer_format_type, conv2d_20_t_out_0_ptr_s8, 1, 1792, conv2d_20_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(20, 1, {(stai_ptr) conv2d_20_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_20 */
  if (!gs_cubeai_layer_done(18U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_21_pad_before */
  {
    
  forward_lite_pad_conv2d_21_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_21_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_21 */
  {
      const ai_i8* conv2d_21_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    const ai_i8* conv2d_21_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 76088);
    const ai_i32* conv2d_21_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 77240);
    ai_i8* conv2d_21_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 14336);
    ai_i16* conv2d_21_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 9984);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(21, 1, {(stai_ptr) conv2d_21_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_21_t_in_0_ptr_const_s8, conv2d_21_t_in_0_shape_w_const_u16, conv2d_21_t_in_0_shape_h_const_u16, conv2d_21_t_in_0_shape_ch_const_u16, conv2d_21_t_weight_0_ptr_const_s8, conv2d_21_l_stride_1_const_u16, conv2d_21_l_stride_0_const_u16, conv2d_21_t_weight_1_ptr_const_s32, conv2d_21_t_in_0_fmt_zero_const_s8, conv2d_21_t_out_0_fmt_zero_const_s8, conv2d_21_t_in_0_fmt_scale_const_f32, conv2d_21_t_out_0_fmt_scale_const_f32, conv2d_21_t_weight_0_fmt_scale_const_f32, conv2d_21_t_out_0_ptr_s8, conv2d_21_t_out_0_shape_w_const_u16, conv2d_21_t_out_0_shape_h_const_u16, 0, 4352, conv2d_21_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(21, 1, {(stai_ptr) conv2d_21_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_21 */
  if (!gs_cubeai_layer_done(19U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_22 */
  {
      const ai_i8* conv2d_22_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 14336);
    const ai_i8* conv2d_22_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 77752);
    const ai_i32* conv2d_22_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 94136);
    ai_i8* conv2d_22_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    ai_i16* conv2d_22_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(22, 1, {(stai_ptr) conv2d_22_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_22_t_in_0_ptr_const_s8, conv2d_22_t_in_0_shape_w_const_u16, conv2d_22_t_in_0_shape_h_const_u16, conv2d_22_l_stride_1_const_u16, conv2d_22_l_stride_0_const_u16, conv2d_22_t_in_0_shape_ch_const_u16, conv2d_22_t_weight_0_ptr_const_s8, conv2d_22_t_out_0_shape_ch_const_u16, conv2d_22_t_weight_1_ptr_const_s32, conv2d_22_t_in_0_fmt_zero_const_s8, conv2d_22_t_out_0_fmt_zero_const_s8, conv2d_22_t_in_0_fmt_scale_const_f32, conv2d_22_t_out_0_fmt_scale_const_f32, conv2d_22_t_weight_0_fmt_scale_const_f32, conv2d_22_l_out_ch_format_const_layer_format_type, conv2d_22_t_out_0_ptr_s8, 1, 1792, conv2d_22_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(22, 1, {(stai_ptr) conv2d_22_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_22 */
  if (!gs_cubeai_layer_done(20U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_23_pad_before */
  {
    
  forward_lite_pad_conv2d_23_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_23_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_23 */
  {
      const ai_i8* conv2d_23_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    const ai_i8* conv2d_23_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 94648);
    const ai_i32* conv2d_23_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 95800);
    ai_i8* conv2d_23_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 14336);
    ai_i16* conv2d_23_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 9984);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(23, 1, {(stai_ptr) conv2d_23_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_23_t_in_0_ptr_const_s8, conv2d_23_t_in_0_shape_w_const_u16, conv2d_23_t_in_0_shape_h_const_u16, conv2d_23_t_in_0_shape_ch_const_u16, conv2d_23_t_weight_0_ptr_const_s8, conv2d_23_l_stride_1_const_u16, conv2d_23_l_stride_0_const_u16, conv2d_23_t_weight_1_ptr_const_s32, conv2d_23_t_in_0_fmt_zero_const_s8, conv2d_23_t_out_0_fmt_zero_const_s8, conv2d_23_t_in_0_fmt_scale_const_f32, conv2d_23_t_out_0_fmt_scale_const_f32, conv2d_23_t_weight_0_fmt_scale_const_f32, conv2d_23_t_out_0_ptr_s8, conv2d_23_t_out_0_shape_w_const_u16, conv2d_23_t_out_0_shape_h_const_u16, 0, 4352, conv2d_23_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(23, 1, {(stai_ptr) conv2d_23_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_23 */
  if (!gs_cubeai_layer_done(21U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_24 */
  {
      const ai_i8* conv2d_24_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 14336);
    const ai_i8* conv2d_24_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 96312);
    const ai_i32* conv2d_24_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 112696);
    ai_i8* conv2d_24_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    ai_i16* conv2d_24_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 0);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(24, 1, {(stai_ptr) conv2d_24_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_24_t_in_0_ptr_const_s8, conv2d_24_t_in_0_shape_w_const_u16, conv2d_24_t_in_0_shape_h_const_u16, conv2d_24_l_stride_1_const_u16, conv2d_24_l_stride_0_const_u16, conv2d_24_t_in_0_shape_ch_const_u16, conv2d_24_t_weight_0_ptr_const_s8, conv2d_24_t_out_0_shape_ch_const_u16, conv2d_24_t_weight_1_ptr_const_s32, conv2d_24_t_in_0_fmt_zero_const_s8, conv2d_24_t_out_0_fmt_zero_const_s8, conv2d_24_t_in_0_fmt_scale_const_f32, conv2d_24_t_out_0_fmt_scale_const_f32, conv2d_24_t_weight_0_fmt_scale_const_f32, conv2d_24_l_out_ch_format_const_layer_format_type, conv2d_24_t_out_0_ptr_s8, 1, 1792, conv2d_24_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(24, 1, {(stai_ptr) conv2d_24_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_24 */
  if (!gs_cubeai_layer_done(22U, 4608U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_25_pad_before */
  {
    
  forward_lite_pad_conv2d_25_pad_before(net_ctx);
  }
  /* LITE_KERNEL_SECTION END conv2d_25_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_25 */
  {
      const ai_i8* conv2d_25_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 1792);
    const ai_i8* conv2d_25_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 113208);
    const ai_i32* conv2d_25_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 114360);
    ai_i8* conv2d_25_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 0);
    ai_i16* conv2d_25_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 9984);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(25, 1, {(stai_ptr) conv2d_25_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_ch1st_sssa8_ch(conv2d_25_t_in_0_ptr_const_s8, conv2d_25_t_in_0_shape_w_const_u16, conv2d_25_t_in_0_shape_h_const_u16, conv2d_25_t_in_0_shape_ch_const_u16, conv2d_25_t_weight_0_ptr_const_s8, conv2d_25_l_stride_1_const_u16, conv2d_25_l_stride_0_const_u16, conv2d_25_t_weight_1_ptr_const_s32, conv2d_25_t_in_0_fmt_zero_const_s8, conv2d_25_t_out_0_fmt_zero_const_s8, conv2d_25_t_in_0_fmt_scale_const_f32, conv2d_25_t_out_0_fmt_scale_const_f32, conv2d_25_t_weight_0_fmt_scale_const_f32, conv2d_25_t_out_0_ptr_s8, conv2d_25_t_out_0_shape_w_const_u16, conv2d_25_t_out_0_shape_h_const_u16, 0, 4352, conv2d_25_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(25, 1, {(stai_ptr) conv2d_25_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_25 */
  if (!gs_cubeai_layer_done(23U, 1152U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_26 */
  {
      const ai_i8* conv2d_26_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 0);
    const ai_i8* conv2d_26_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 114872);
    const ai_i32* conv2d_26_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 147640);
    ai_i8* conv2d_26_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 4224);
    ai_i16* conv2d_26_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 1152);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(26, 1, {(stai_ptr) conv2d_26_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_26_t_in_0_ptr_const_s8, conv2d_26_t_in_0_shape_w_const_u16, conv2d_26_t_in_0_shape_h_const_u16, conv2d_26_l_stride_1_const_u16, conv2d_26_l_stride_0_const_u16, conv2d_26_t_in_0_shape_ch_const_u16, conv2d_26_t_weight_0_ptr_const_s8, conv2d_26_t_out_0_shape_ch_const_u16, conv2d_26_t_weight_1_ptr_const_s32, conv2d_26_t_in_0_fmt_zero_const_s8, conv2d_26_t_out_0_fmt_zero_const_s8, conv2d_26_t_in_0_fmt_scale_const_f32, conv2d_26_t_out_0_fmt_scale_const_f32, conv2d_26_t_weight_0_fmt_scale_const_f32, conv2d_26_l_out_ch_format_const_layer_format_type, conv2d_26_t_out_0_ptr_s8, 1, 3072, conv2d_26_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(26, 1, {(stai_ptr) conv2d_26_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_26 */
  if (!gs_cubeai_layer_done(24U, 2304U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_27_pad_before */
  {
      const ai_ptr conv2d_27_pad_before_t_in_0_ptr_const_ptr = (ai_ptr)(net_ctx->_activations[0] + 4224);
    ai_ptr conv2d_27_pad_before_t_out_0_ptr_ptr = (ai_ptr)(net_ctx->_activations[0] + 6528);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(27, 1, {(stai_ptr) conv2d_27_pad_before_t_in_0_ptr_const_ptr});
    
  forward_lite_pad_constant(conv2d_27_pad_before_t_in_0_ptr_const_ptr, conv2d_27_pad_before_t_out_0_ptr_ptr, (ai_handle)(conv2d_27_pad_before_v_pad_constant_value_const_s8), conv2d_27_pad_before_t_in_0_fmt_bitsize_const_s16, conv2d_27_pad_before_t_in_0_shape_h_const_u32, (ai_i32)(1), (ai_i32)(768), (ai_i32)(1280), (ai_i32)(1280), (ai_i32)(256), (ai_i32)(256));
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(27, 1, {(stai_ptr) conv2d_27_pad_before_t_out_0_ptr_ptr});
  }
  /* LITE_KERNEL_SECTION END conv2d_27_pad_before */
  /* LITE_KERNEL_SECTION BEGIN conv2d_27 */
  {
      const ai_i8* conv2d_27_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 6528);
    const ai_i8* conv2d_27_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 148664);
    const ai_i32* conv2d_27_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 150968);
    ai_i8* conv2d_27_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 0);
    ai_i16* conv2d_27_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 12928);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(27, 1, {(stai_ptr) conv2d_27_t_in_0_ptr_const_s8});
    
  forward_lite_dw_3x3_sssa8_ch(conv2d_27_t_in_0_ptr_const_s8, conv2d_27_t_in_0_shape_w_const_u16, conv2d_27_t_in_0_shape_h_const_u16, conv2d_27_t_in_0_shape_ch_const_u16, conv2d_27_t_weight_0_ptr_const_s8, conv2d_27_l_stride_1_const_u16, conv2d_27_l_stride_0_const_u16, conv2d_27_t_weight_1_ptr_const_s32, conv2d_27_t_in_0_fmt_zero_const_s8, conv2d_27_t_out_0_fmt_zero_const_s8, conv2d_27_t_in_0_fmt_scale_const_f32, conv2d_27_t_out_0_fmt_scale_const_f32, conv2d_27_t_weight_0_fmt_scale_const_f32, conv2d_27_t_out_0_ptr_s8, conv2d_27_t_out_0_shape_w_const_u16, conv2d_27_t_out_0_shape_h_const_u16, 0, 9473, conv2d_27_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(27, 1, {(stai_ptr) conv2d_27_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_27 */
  if (!gs_cubeai_layer_done(25U, 2304U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN conv2d_28 */
  {
      const ai_i8* conv2d_28_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 0);
    const ai_i8* conv2d_28_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 151992);
    const ai_i32* conv2d_28_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 217528);
    ai_i8* conv2d_28_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_activations[0] + 5888);
    ai_i16* conv2d_28_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 2304);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(28, 1, {(stai_ptr) conv2d_28_t_in_0_ptr_const_s8});
    
  forward_lite_pw_sssa8_ch(conv2d_28_t_in_0_ptr_const_s8, conv2d_28_t_in_0_shape_w_const_u16, conv2d_28_t_in_0_shape_h_const_u16, conv2d_28_l_stride_1_const_u16, conv2d_28_l_stride_0_const_u16, conv2d_28_t_in_0_shape_ch_const_u16, conv2d_28_t_weight_0_ptr_const_s8, conv2d_28_t_out_0_shape_ch_const_u16, conv2d_28_t_weight_1_ptr_const_s32, conv2d_28_t_in_0_fmt_zero_const_s8, conv2d_28_t_out_0_fmt_zero_const_s8, conv2d_28_t_in_0_fmt_scale_const_f32, conv2d_28_t_out_0_fmt_scale_const_f32, conv2d_28_t_weight_0_fmt_scale_const_f32, conv2d_28_l_out_ch_format_const_layer_format_type, conv2d_28_t_out_0_ptr_s8, 1, 3584, conv2d_28_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(28, 1, {(stai_ptr) conv2d_28_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END conv2d_28 */
  if (!gs_cubeai_layer_done(26U, 2304U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN pool_29 */
  {
    
  forward_lite_ap_integer_INT8_pool_29(net_ctx);
  }
  /* LITE_KERNEL_SECTION END pool_29 */
  if (!gs_cubeai_layer_done(27U, 256U)) { return STAI_ERROR_GENERIC; }
  /* LITE_KERNEL_SECTION BEGIN gemm_30 */
  {
      ai_i8* gemm_30_t_out_0_ptr_s8 = (ai_i8*)(net_ctx->_outputs[0] + 0);
    const ai_i8* gemm_30_t_in_0_ptr_const_s8 = (ai_i8*)(net_ctx->_activations[0] + 0);
    const ai_i8* gemm_30_t_weight_0_ptr_const_s8 = (ai_i8*)(net_ctx->_weights[0] + 218552);
    const ai_i32* gemm_30_t_weight_1_ptr_const_s32 = (ai_i32*)(net_ctx->_weights[0] + 220088);
    ai_i16* gemm_30_t_scratch_0_ptr_s16 = (ai_i16*)(net_ctx->_activations[0] + 256);
  
  _STAI_GS_NETWORK_EVENT_NODE_START_CB(30, 1, {(stai_ptr) gemm_30_t_in_0_ptr_const_s8});
    
  forward_lite_dense_is8os8ws8(gemm_30_t_out_0_ptr_s8, gemm_30_t_in_0_ptr_const_s8, gemm_30_t_weight_0_ptr_const_s8, gemm_30_t_weight_1_ptr_const_s32, gemm_30_t_in_0_fmt_zero_const_s8, gemm_30_t_out_0_fmt_zero_const_s8, gemm_30_t_in_0_shape_ch_const_u16, gemm_30_t_out_0_shape_ch_const_u16, gemm_30_t_out_0_shape_h_w_prod_const_u32, gemm_30_t_in_0_fmt_scale_const_f32, gemm_30_t_out_0_fmt_scale_const_f32, gemm_30_t_weight_0_fmt_scale_const_f32, gemm_30_t_scratch_0_ptr_s16);
    
  _STAI_GS_NETWORK_EVENT_NODE_STOP_CB(30, 1, {(stai_ptr) gemm_30_t_out_0_ptr_s8});
  }
  /* LITE_KERNEL_SECTION END gemm_30 */
  if (!gs_cubeai_layer_done(28U, 6U)) { return STAI_ERROR_GENERIC; }
  return net_ctx->_return_code;
}

/*****************************************************************************/
/*  Getters APIs Section  */
STAI_API_ENTRY
stai_size stai_gs_network_get_context_size()
{
  return (stai_size)STAI_GS_NETWORK_CONTEXT_SIZE;
}

#if defined(HAVE_GS_NETWORK_INFO)
STAI_API_ENTRY
stai_return_code stai_gs_network_get_info(
  stai_network* network,
  stai_network_info* info)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
  _STAI_SET_ERROR(net_ctx, info==NULL, STAI_ERROR_NETWORK_INVALID_INFO, net_ctx->_return_code)

  // Copy of network info struct
  *info = g_gs_network_info;

  return STAI_SUCCESS;
}
#endif


STAI_API_ENTRY
stai_return_code stai_gs_network_get_activations(
  stai_network* network, stai_ptr* activations, stai_size* n_activations)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)

  _STAI_SET_ERROR(net_ctx, !n_activations, STAI_ERROR_NETWORK_INVALID_API_ARGUMENTS, net_ctx->_return_code)
  *n_activations = STAI_GS_NETWORK_ACTIVATIONS_NUM;
for (stai_size idx=0; activations && (idx<STAI_GS_NETWORK_ACTIVATIONS_NUM); idx++) {
    // get address of the activations buffers
    activations[idx] = net_ctx->_activations[idx];
  }return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_get_weights(
  stai_network* network, stai_ptr* weights, stai_size* n_weights)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
  _STAI_SET_ERROR(net_ctx, !n_weights, STAI_ERROR_NETWORK_INVALID_API_ARGUMENTS, net_ctx->_return_code)
  *n_weights = STAI_GS_NETWORK_WEIGHTS_NUM;
for (stai_size idx=0; weights && (idx<STAI_GS_NETWORK_WEIGHTS_NUM); idx++) {
    // get address of the weights buffers
    weights[idx] = net_ctx->_weights[idx];
  }return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_get_inputs(
  stai_network* network, stai_ptr* inputs, stai_size* n_inputs)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
  _STAI_SET_ERROR(net_ctx, !n_inputs, STAI_ERROR_NETWORK_INVALID_API_ARGUMENTS, net_ctx->_return_code)
  *n_inputs = STAI_GS_NETWORK_IN_NUM;
  for (stai_size idx=0; inputs && (idx<STAI_GS_NETWORK_IN_NUM); idx++) {
    inputs[idx] = net_ctx->_inputs[idx];
  }
  return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_get_outputs(
  stai_network* network, stai_ptr* outputs, stai_size* n_outputs)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
  _STAI_SET_ERROR(net_ctx, !n_outputs, STAI_ERROR_NETWORK_INVALID_API_ARGUMENTS, net_ctx->_return_code)
  *n_outputs = STAI_GS_NETWORK_OUT_NUM;
  for (stai_size idx=0; outputs && (idx<STAI_GS_NETWORK_OUT_NUM); idx++) {
    outputs[idx] = net_ctx->_outputs[idx];
  }
  return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_get_error(
  stai_network* network)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)

  /* return 1st generated error or STAI_SUCCESS if no errors so far */
  return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_get_states(
  stai_network* network, stai_ptr* states, stai_size* n_states)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
  _STAI_SET_ERROR(net_ctx, !n_states, STAI_ERROR_NETWORK_INVALID_API_ARGUMENTS, net_ctx->_return_code)
  /* get the number of internals states (supporting multi-heap also for internal states) */
  *n_states = STAI_GS_NETWORK_STATES_NUM;

  STAI_UNUSED(states)
return net_ctx->_return_code;
}


/*****************************************************************************/
/*  Setters APIs Section  */

STAI_API_ENTRY
stai_return_code stai_gs_network_set_activations(
  stai_network* network,
  const stai_ptr* activations,
  const stai_size n_activations)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
const uintptr_t _activations_alignment[] = STAI_GS_NETWORK_ACTIVATIONS_ALIGNMENTS;
  STAI_PRINT("  [stai_gs_network_set_activations] network(%p) activations[%d]: %p\n\n", net_ctx, n_activations, activations)
  _STAI_SET_ERROR(net_ctx, !activations,
                  STAI_ERROR_NETWORK_INVALID_API_ARGUMENTS, net_ctx->_return_code)
  _STAI_SET_ERROR(net_ctx, n_activations!=STAI_GS_NETWORK_ACTIVATIONS_NUM,
                  STAI_ERROR_NETWORK_INVALID_ACTIVATIONS_NUM, net_ctx->_return_code)

  for (stai_size idx=0; activations && idx<STAI_GS_NETWORK_ACTIVATIONS_NUM; idx++) {
    STAI_PRINT("  activation[%d]: %p\n", idx, activations[idx])
    _STAI_SET_ERROR(net_ctx, activations[idx]==NULL,
                    STAI_ERROR_NETWORK_INVALID_ACTIVATIONS_PTR, net_ctx->_return_code)
    _STAI_SET_ERROR(net_ctx, ((uintptr_t)activations[idx]) & (_activations_alignment[idx]-1),
                    STAI_ERROR_INVALID_BUFFER_ALIGNMENT, net_ctx->_return_code)
    net_ctx->_activations[idx] = activations[idx];
  }_stai_gs_network_check(net_ctx);
  return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_set_weights(
  stai_network* network,
  const stai_ptr* weights,
  const stai_size n_weights)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
const uintptr_t _weights_alignment[] = STAI_GS_NETWORK_WEIGHTS_ALIGNMENTS;
  _STAI_SET_ERROR(net_ctx, !weights,
                  STAI_ERROR_NETWORK_INVALID_API_ARGUMENTS, net_ctx->_return_code)
  _STAI_SET_ERROR(net_ctx, n_weights!=STAI_GS_NETWORK_WEIGHTS_NUM,
                  STAI_ERROR_NETWORK_INVALID_WEIGHTS_NUM, net_ctx->_return_code)
  for (stai_size idx=0; weights && idx<STAI_GS_NETWORK_WEIGHTS_NUM; idx++) {
    STAI_PRINT("  weight[%d]: %p\n", idx, weights[idx])
    _STAI_SET_ERROR(net_ctx, weights[idx]==NULL,
                    STAI_ERROR_NETWORK_INVALID_WEIGHTS_PTR, net_ctx->_return_code)
    _STAI_SET_ERROR(net_ctx, ((uintptr_t)weights[idx]) & (_weights_alignment[idx]-1),
                    STAI_ERROR_INVALID_BUFFER_ALIGNMENT, net_ctx->_return_code)
    net_ctx->_weights[idx] = weights[idx];
  }_stai_gs_network_check(net_ctx);
  return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_set_inputs(
  stai_network* network,
  const stai_ptr* inputs,
  const stai_size n_inputs)
{
  const uintptr_t _inputs_alignment[] = STAI_GS_NETWORK_IN_ALIGNMENTS;
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
  _STAI_SET_ERROR(net_ctx, !inputs,
                  STAI_ERROR_NETWORK_INVALID_API_ARGUMENTS, net_ctx->_return_code)
  _STAI_SET_ERROR(net_ctx, n_inputs!=STAI_GS_NETWORK_IN_NUM,
                  STAI_ERROR_NETWORK_INVALID_IN_NUM, net_ctx->_return_code)

  for (stai_size idx=0; inputs && idx<STAI_GS_NETWORK_IN_NUM; idx++) {
    STAI_PRINT("  input[%d]: %p\n", idx, inputs[idx])
    _STAI_SET_ERROR(net_ctx, inputs[idx]==NULL,
                    STAI_ERROR_NETWORK_INVALID_IN_PTR, net_ctx->_return_code)
    _STAI_SET_ERROR(net_ctx, ((uintptr_t)inputs[idx]) & (_inputs_alignment[idx]-1),
                    STAI_ERROR_INVALID_BUFFER_ALIGNMENT, net_ctx->_return_code)
    net_ctx->_inputs[idx] = inputs[idx];
  }

  _stai_gs_network_check(net_ctx);
  return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_set_outputs(
  stai_network* network,
  const stai_ptr* outputs,
  const stai_size n_outputs)
{
  const uintptr_t _outputs_alignment[] = STAI_GS_NETWORK_OUT_ALIGNMENTS;
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
  _STAI_SET_ERROR(net_ctx, !outputs,
                  STAI_ERROR_NETWORK_INVALID_API_ARGUMENTS, net_ctx->_return_code)
  _STAI_SET_ERROR(net_ctx, n_outputs!=STAI_GS_NETWORK_OUT_NUM,
                  STAI_ERROR_NETWORK_INVALID_OUT_NUM, net_ctx->_return_code)

  for (stai_size idx=0; outputs && idx<n_outputs; idx++) {
    STAI_PRINT("  output[%d]: %p\n", idx, outputs[idx])
    _STAI_SET_ERROR(net_ctx, outputs[idx]==NULL,
                    STAI_ERROR_NETWORK_INVALID_OUT_PTR, net_ctx->_return_code)
    _STAI_SET_ERROR(net_ctx, ((uintptr_t)outputs[idx]) & (_outputs_alignment[idx]-1),
                    STAI_ERROR_INVALID_BUFFER_ALIGNMENT, net_ctx->_return_code)
    net_ctx->_outputs[idx] = outputs[idx];
  }

  _stai_gs_network_check(net_ctx);
  return net_ctx->_return_code;
}


STAI_API_ENTRY
stai_return_code stai_gs_network_set_states(
  stai_network* network,
  const stai_ptr* states,
  const stai_size n_states)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)

  STAI_UNUSED(states)
  STAI_UNUSED(n_states)
_stai_gs_network_check(net_ctx);
  return net_ctx->_return_code;
}

STAI_API_ENTRY
stai_return_code stai_gs_network_set_callback(
  stai_network* network, const stai_event_cb cb, void* cb_cookie)
{
  _STAI_CONTEXT_ACQUIRE(net_ctx, network)
  STAI_PRINT("  set_callback %p cb %p cookie %p\n", net_ctx, cb, cb_cookie)
  // _STAI_SET_ERROR(net_ctx, cb==NULL, STAI_ERROR_NETWORK_INVALID_CALLBACK, net_ctx->_return_code)
  net_ctx->_callback = cb;
  net_ctx->_callback_cookie = cb_cookie;
  return net_ctx->_return_code;
}

#undef _STAI_SET_ERROR
#undef _STAI_CONTEXT_ALIGNMENT
#undef _STAI_CONTEXT_ACQUIRE
#undef _STAI_GS_NETWORK_EVENT_NODE_START_CB
#undef _STAI_GS_NETWORK_EVENT_NODE_STOP_CB
#undef _STAI_GS_NETWORK_MODEL_SIGNATURE
#undef _STAI_GS_NETWORK_DATETIME
#undef _STAI_GS_NETWORK_COMPILE_DATETIME

