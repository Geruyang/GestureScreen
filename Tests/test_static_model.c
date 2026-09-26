#include "gs_static_recognition.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    const float scale = 0.08847017586231232f;
    gs_static_result_t result;
    int8_t logits[GS_STATIC_CLASS_COUNT];
    unsigned target, i;

    for (target = 0U; target < GS_STATIC_CLASS_COUNT; ++target) {
        memset(&result, 0, sizeof result);
        memset(logits, -128, sizeof logits);
        logits[target] = 127;
        assert(gs_static_decode_logits(logits, scale, -6, &result) == GS_AI_OK);
        assert(result.class_index == target && result.confidence_permille == 1000U);
        assert(result.scores_valid == 1U && result.scores[target] > 0.999f);
        assert(result.status == (uint32_t)(target < GS_STATIC_UNKNOWN ?
            GS_STATIC_IDENTIFIED : GS_STATIC_NO_TARGET));
    }

    memset(logits, 12, sizeof logits);
    assert(gs_static_decode_logits(logits, scale, -6, &result) == GS_AI_OK);
    assert(result.status == GS_STATIC_UNCERTAIN);
    assert(result.confidence_permille == 167U && result.margin_permille == 0U);
    for (i = 0U; i < GS_STATIC_CLASS_COUNT; ++i) {
        assert(result.scores[i] > 0.166f && result.scores[i] < 0.168f);
    }

    /* A shared zero point cancels from Softmax; both legal values decode alike. */
    {
        gs_static_result_t other;
        memset(logits, -20, sizeof logits); logits[GS_STATIC_PALM] = 20;
        assert(gs_static_decode_logits(logits, scale, -128, &result) == GS_AI_OK);
        assert(gs_static_decode_logits(logits, scale, 127, &other) == GS_AI_OK);
        assert(result.class_index == other.class_index);
        assert(result.confidence_permille == other.confidence_permille);
        assert(!memcmp(result.scores, other.scores, sizeof result.scores));
    }

    assert(gs_static_decode_logits(NULL, scale, -6, &result) == GS_AI_INVALID_ARGUMENT);
    assert(gs_static_decode_logits(logits, 0.0f, -6, &result) == GS_AI_INVALID_ARGUMENT);
    assert(gs_static_decode_logits(logits, scale, 128, &result) == GS_AI_INVALID_ARGUMENT);
    assert(gs_static_model_status() == GS_AI_UNAVAILABLE);

    result.frame_id = 1U; result.capture_ms = UINT32_MAX - 50U;
    result.status = GS_STATIC_IDENTIFIED; result.scores_valid = 1U;
    result.confidence_permille = 999U;
    gs_static_expire(&result, 1449U);
    assert(result.status == GS_STATIC_IDENTIFIED && result.scores_valid == 1U);
    gs_static_expire(&result, 1450U);
    assert(result.status == GS_STATIC_STALE && result.confidence_permille == 0U);
    assert(result.scores_valid == 0U);

    puts("PASS: six-class quantized-logit decode, fixed label order, target/UNKNOWN, thresholds, guards and TTL; no accuracy claim.");
    return 0;
}
