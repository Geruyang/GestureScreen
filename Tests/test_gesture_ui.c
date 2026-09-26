/* 使用合成数据验证状态机，不属于模型准确率测试或实板测试。 */
#include "gs_gesture.h"
#include "gs_ui.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    gs_gesture_t gesture;
    gs_ui_command_t command;
    uint32_t next_frame;
    uint32_t generation;
} gs_fixture_t;

static gs_gesture_observation_t gs_test_observation(gs_gesture_class_t label,
                                                   uint32_t frame, uint32_t time)
{
    gs_gesture_observation_t observation;
    memset(&observation, 0, sizeof(observation));
    observation.frame_id = frame;
    observation.capture_ms = time;
    observation.valid = true;
    observation.scores[label] = 0.99f;
    observation.scores[label == GS_CLASS_UNKNOWN ? GS_CLASS_FIST : GS_CLASS_UNKNOWN] = 0.01f;
    return observation;
}

static void gs_test_init(gs_fixture_t *fixture)
{
    memset(fixture, 0, sizeof(*fixture));
    assert(gs_gesture_init(&fixture->gesture, NULL));
    fixture->next_frame = 1U;
    fixture->generation = 1U;
    gs_gesture_set_enabled(&fixture->gesture, true);
}

static bool gs_test_feed(gs_fixture_t *fixture, gs_gesture_class_t label, uint32_t time)
{
    gs_gesture_observation_t observation =
        gs_test_observation(label, fixture->next_frame++, time);
    return gs_gesture_process(&fixture->gesture, &observation, time,
                               fixture->generation, &fixture->command);
}

static void gs_test_clear(gs_fixture_t *fixture, uint32_t time)
{
    assert(!gs_test_feed(fixture, GS_CLASS_UNKNOWN, time));
    assert(!gs_test_feed(fixture, GS_CLASS_UNKNOWN, time + 200U));
    assert(!gs_test_feed(fixture, GS_CLASS_UNKNOWN, time + 400U));
    assert(!gs_test_feed(fixture, GS_CLASS_UNKNOWN, time + 600U));
    assert(fixture->gesture.state == GS_GESTURE_READY);
}

static void gs_test_emit(gs_fixture_t *fixture, gs_gesture_class_t label, uint32_t time)
{
    assert(!gs_test_feed(fixture, label, time));
    assert(!gs_test_feed(fixture, label, time + 200U));
    assert(gs_test_feed(fixture, label, time + 400U));
    assert(fixture->gesture.state == GS_GESTURE_WAIT_CLEAR);
}

static void gs_test_startup_and_hold(void)
{
    gs_fixture_t fixture;
    uint32_t time;
    gs_test_init(&fixture);
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
    for (time = 0U; time <= 1000U; time += 200U) {
        assert(!gs_test_feed(&fixture, GS_CLASS_PALM, time));
    }
    assert(fixture.gesture.state == GS_GESTURE_WAIT_CLEAR);
    gs_test_clear(&fixture, 1200U);
    gs_test_emit(&fixture, GS_CLASS_POINT_RIGHT, 2000U);
    assert(fixture.command.action == GS_UI_PREVIOUS);
    assert(fixture.command.sequence == 1U);
    for (time = 2600U; time <= 12600U; time += 200U) {
        assert(!gs_test_feed(&fixture, GS_CLASS_POINT_RIGHT, time));
    }
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 12800U));
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 13000U));
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 13200U));
    gs_test_clear(&fixture, 13400U);
    gs_test_emit(&fixture, GS_CLASS_PALM, 14200U);
    assert(fixture.command.action == GS_UI_UP);
    assert(fixture.command.sequence == 2U);
}

static void gs_test_all_five_mappings(void)
{
    static const gs_ui_action_t expected[] = {
        GS_UI_NEXT, GS_UI_PREVIOUS, GS_UI_HOME, GS_UI_UP, GS_UI_ENTER
    };
    unsigned int label;
    for (label = 0U; label < sizeof(expected) / sizeof(expected[0]); ++label) {
        gs_fixture_t fixture;
        gs_test_init(&fixture);
        gs_test_clear(&fixture, 0U);
        gs_test_emit(&fixture, (gs_gesture_class_t)label, 800U);
        assert(fixture.command.action == expected[label]);
    }
}

static void gs_test_minimum_frames_and_time(void)
{
    gs_fixture_t fixture;
    gs_test_init(&fixture);
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 0U));
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 300U));
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 600U));
    assert(fixture.gesture.state == GS_GESTURE_WAIT_CLEAR);
    assert(gs_gesture_progress(&fixture.gesture) == 750U);
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 650U));
    assert(fixture.gesture.state == GS_GESTURE_READY);
    assert(!gs_test_feed(&fixture, GS_CLASS_FIST, 800U));
    assert(!gs_test_feed(&fixture, GS_CLASS_FIST, 900U));
    assert(!gs_test_feed(&fixture, GS_CLASS_FIST, 1000U));
    assert(fixture.gesture.state == GS_GESTURE_CANDIDATE);
    assert(gs_gesture_progress(&fixture.gesture) == 500U);
    gs_gesture_tick(&fixture.gesture, 1100U, fixture.generation);
    assert(gs_gesture_progress(&fixture.gesture) == 500U);
    assert(!gs_test_feed(&fixture, GS_CLASS_FIST, 1199U));
    assert(gs_test_feed(&fixture, GS_CLASS_FIST, 1200U));
}

static void gs_test_deduplication_and_age(void)
{
    gs_fixture_t fixture;
    gs_gesture_observation_t observation;
    gs_test_init(&fixture);
    gs_test_clear(&fixture, 0U);
    observation = gs_test_observation(GS_CLASS_FIST, fixture.next_frame++, 800U);
    assert(!gs_gesture_process(&fixture.gesture, &observation, 800U, 1U, &fixture.command));
    assert(!gs_gesture_process(&fixture.gesture, &observation, 900U, 1U, &fixture.command));
    assert(!gs_gesture_process(&fixture.gesture, &observation, 1000U, 1U, &fixture.command));
    assert(fixture.gesture.evidence_frames == 1U);
    assert(fixture.gesture.duplicate_count == 2U);
    assert(!gs_gesture_process(&fixture.gesture, &observation, 1101U, 1U, &fixture.command));
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
    assert(fixture.gesture.evidence_frames == 0U);
    /* 故障后必须先收到新的有效图像，才能开始累计撤手证据。 */
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 1102U));
    assert(fixture.gesture.state == GS_GESTURE_WAIT_CLEAR);
    assert(fixture.gesture.evidence_frames == 1U);
}

static void gs_test_age_boundary_and_future_recovery(void)
{
    gs_fixture_t fixture;
    gs_gesture_observation_t observation;
    uint32_t time;
    gs_test_init(&fixture);
    for (time = 0U; time <= 600U; time += 200U) {
        observation = gs_test_observation(GS_CLASS_UNKNOWN, fixture.next_frame++, time);
        assert(!gs_gesture_process(&fixture.gesture, &observation, time + 300U,
                                   1U, &fixture.command));
    }
    assert(fixture.gesture.state == GS_GESTURE_READY);
    observation = gs_test_observation(GS_CLASS_FIST, fixture.next_frame++, 10000U);
    assert(!gs_gesture_process(&fixture.gesture, &observation, 901U, 1U, &fixture.command));
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
    observation = gs_test_observation(GS_CLASS_UNKNOWN, fixture.next_frame++, 800U);
    assert(!gs_gesture_process(&fixture.gesture, &observation, 950U, 1U, &fixture.command));
    assert(fixture.gesture.state == GS_GESTURE_WAIT_CLEAR);
    assert(fixture.gesture.evidence_frames == 1U);
}

static void gs_test_gap_timeout_and_recovery(void)
{
    gs_fixture_t fixture;
    gs_test_init(&fixture);
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 0U));
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 200U));
    gs_gesture_tick(&fixture.gesture, 550U, 1U);
    assert(fixture.gesture.state == GS_GESTURE_WAIT_CLEAR);
    gs_gesture_tick(&fixture.gesture, 551U, 1U);
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
    assert(fixture.gesture.evidence_frames == 0U);
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 600U));
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
    gs_test_clear(&fixture, 800U);
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 1600U));
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 1950U));
    assert(gs_test_feed(&fixture, GS_CLASS_PALM, 2000U));
}

static void gs_test_capture_gap_even_with_timely_delivery(void)
{
    gs_fixture_t fixture;
    gs_gesture_observation_t observation;
    gs_test_init(&fixture);
    observation = gs_test_observation(GS_CLASS_UNKNOWN, fixture.next_frame++, 0U);
    assert(!gs_gesture_process(&fixture.gesture, &observation, 200U, 1U, &fixture.command));
    observation = gs_test_observation(GS_CLASS_UNKNOWN, fixture.next_frame++, 400U);
    assert(!gs_gesture_process(&fixture.gesture, &observation, 400U, 1U, &fixture.command));
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
}

static void gs_test_sequence_and_timestamp_faults(void)
{
    gs_fixture_t fixture;
    gs_gesture_observation_t observation;
    gs_test_init(&fixture);
    gs_test_clear(&fixture, 0U);
    observation = gs_test_observation(GS_CLASS_PALM, 3U, 800U);
    assert(!gs_gesture_process(&fixture.gesture, &observation, 800U, 1U, &fixture.command));
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 800U));
    assert(fixture.gesture.state == GS_GESTURE_WAIT_CLEAR);
    observation = gs_test_observation(GS_CLASS_UNKNOWN, fixture.next_frame++, 800U);
    assert(!gs_gesture_process(&fixture.gesture, &observation, 801U, 1U, &fixture.command));
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
}

static void gs_test_rejection_and_class_change(void)
{
    gs_fixture_t fixture;
    gs_gesture_observation_t observation;
    gs_test_init(&fixture);
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 0U));
    assert(!gs_test_feed(&fixture, GS_CLASS_UNKNOWN, 200U));
    assert(!gs_test_feed(&fixture, GS_CLASS_FIST, 400U));
    assert(fixture.gesture.evidence_frames == 0U);
    gs_test_clear(&fixture, 600U);
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 1400U));
    assert(!gs_test_feed(&fixture, GS_CLASS_FIST, 1600U));
    assert(fixture.gesture.state == GS_GESTURE_READY);
    assert(!gs_test_feed(&fixture, GS_CLASS_FIST, 1800U));
    observation = gs_test_observation(GS_CLASS_FIST, fixture.next_frame++, 2000U);
    observation.scores[GS_CLASS_FIST] = 0.89f;
    observation.scores[GS_CLASS_UNKNOWN] = 0.11f;
    assert(!gs_gesture_process(&fixture.gesture, &observation, 2000U, 1U, &fixture.command));
    assert(fixture.gesture.state == GS_GESTURE_READY);
    assert(fixture.gesture.evidence_frames == 0U);
}

static void gs_test_invalid_image_and_probabilities(void)
{
    gs_fixture_t fixture;
    gs_gesture_observation_t observation;
    gs_test_init(&fixture);
    gs_test_clear(&fixture, 0U);
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 800U));
    observation = gs_test_observation(GS_CLASS_UNKNOWN, fixture.next_frame++, 1000U);
    observation.valid = false;
    assert(!gs_gesture_process(&fixture.gesture, &observation, 1000U, 1U, &fixture.command));
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
    observation = gs_test_observation(GS_CLASS_UNKNOWN, fixture.next_frame++, 1100U);
    observation.scores[GS_CLASS_UNKNOWN] = NAN;
    assert(!gs_gesture_process(&fixture.gesture, &observation, 1100U, 1U, &fixture.command));
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
    observation = gs_test_observation(GS_CLASS_UNKNOWN, fixture.next_frame++, 1100U);
    observation.scores[GS_CLASS_UNKNOWN] = 0.50f;
    assert(!gs_gesture_process(&fixture.gesture, &observation, 1100U, 1U, &fixture.command));
    assert(fixture.gesture.evidence_frames == 0U);
    gs_gesture_report_fault(&fixture.gesture);
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
}

static void gs_test_generation_and_enable(void)
{
    gs_fixture_t fixture;
    gs_test_init(&fixture);
    gs_test_clear(&fixture, 0U);
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 800U));
    fixture.generation = 2U;
    gs_gesture_tick(&fixture.gesture, 900U, fixture.generation);
    assert(fixture.gesture.state == GS_GESTURE_WAIT_CLEAR);
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 1000U));
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 1200U));
    assert(fixture.gesture.evidence_frames == 0U);
    gs_test_clear(&fixture, 1400U);
    gs_gesture_set_enabled(&fixture.gesture, false);
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 2200U));
    assert(fixture.gesture.state == GS_GESTURE_DISABLED);
    gs_gesture_set_enabled(&fixture.gesture, true);
    assert(!gs_test_feed(&fixture, GS_CLASS_PALM, 2250U));
    assert(fixture.gesture.state == GS_GESTURE_WAIT_CLEAR);
}

static void gs_test_uint32_wrap(void)
{
    gs_fixture_t fixture;
    uint32_t start = UINT32_MAX - 300U;
    gs_test_init(&fixture);
    fixture.next_frame = UINT32_MAX - 2U;
    gs_test_clear(&fixture, start);
    fixture.gesture.next_sequence = UINT32_MAX;
    gs_test_emit(&fixture, GS_CLASS_PALM, start + 800U);
    assert(fixture.command.sequence == UINT32_MAX);
    gs_test_clear(&fixture, start + 1400U);
    gs_test_emit(&fixture, GS_CLASS_PALM, start + 2200U);
    assert(fixture.command.sequence == 1U);
}

static const gs_ui_page_t gs_test_pages[] = {
    {"First", "One"}, {"Second", "Two"}, {"Third", "Three"}
};
static const gs_ui_collection_t gs_test_collections[] = {
    {"Book A", 3U, gs_test_pages, GS_UI_COLLECTION_CONTENT, "Writer A"},
    {"Book B", 3U, gs_test_pages, GS_UI_COLLECTION_CONTENT, "Writer B"}
};

static void gs_test_ui_navigation(void)
{
    gs_ui_t ui;
    uint32_t generation;
    assert(gs_ui_init(&ui, gs_test_collections, 2U, 1000U));
    assert(ui.mode == GS_UI_DIRECTORY && ui.selected == 0U);
    assert(!gs_ui_action_available(&ui, GS_UI_PREVIOUS));
    assert(!gs_ui_action_available(&ui, GS_UI_HOME));
    assert(gs_ui_local_action(&ui, GS_UI_NEXT, 0U) == GS_UI_APPLIED);
    assert(ui.selected == 1U);
    assert(gs_ui_local_action(&ui, GS_UI_NEXT, 1U) == GS_UI_REJECTED_UNAVAILABLE);
    assert(gs_ui_local_action(&ui, GS_UI_PREVIOUS, 2U) == GS_UI_APPLIED);
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 3U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_CATALOG && ui.chapter == 0U);
    assert(gs_ui_local_action(&ui, GS_UI_NEXT, 4U) == GS_UI_APPLIED);
    assert(ui.chapter == 1U);
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 5U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_READER && ui.page == 1U);
    assert(gs_ui_local_action(&ui, GS_UI_NEXT, 6U) == GS_UI_APPLIED);
    assert(ui.page == 2U);
    generation = ui.generation;
    assert(!gs_ui_tick(&ui, 10000U));
    assert(ui.page == 2U && ui.generation == generation);
    assert(gs_ui_local_action(&ui, GS_UI_UP, 7U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_CATALOG && ui.chapter == 2U);
    assert(gs_ui_local_action(&ui, GS_UI_UP, 8U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_DIRECTORY);
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 9U) == GS_UI_APPLIED);
    assert(gs_ui_local_action(&ui, GS_UI_HOME, 10U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_DIRECTORY);
}

static void gs_test_ui_command_revalidation(void)
{
    gs_ui_t ui;
    gs_ui_command_t command;
    assert(gs_ui_init(&ui, gs_test_collections, 2U, 1000U));
    command.action = GS_UI_NEXT;
    command.sequence = 1U;
    command.ui_generation = ui.generation;
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 0U) == GS_UI_APPLIED);
    assert(gs_ui_execute(&ui, &command, 100U) == GS_UI_REJECTED_STALE);
    command.ui_generation = ui.generation;
    assert(gs_ui_execute(&ui, &command, 100U) == GS_UI_REJECTED_DUPLICATE);
    command.sequence = 2U;
    assert(gs_ui_execute(&ui, &command, 100U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_CATALOG && ui.chapter == 1U);
    assert(gs_ui_execute(&ui, &command, 100U) == GS_UI_REJECTED_DUPLICATE);
}

static void gs_test_full_flow_and_neutral_rearm(void)
{
    gs_fixture_t fixture;
    gs_ui_t ui;
    gs_test_init(&fixture);
    assert(gs_ui_init(&ui, gs_test_collections, 2U, 1000U));
    gs_test_clear(&fixture, 0U);
    gs_test_emit(&fixture, GS_CLASS_V_SIGN, 800U);
    assert(gs_ui_execute(&ui, &fixture.command, 1200U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_CATALOG);
    fixture.generation = ui.generation;
    gs_test_clear(&fixture, 1400U);
    gs_test_emit(&fixture, GS_CLASS_V_SIGN, 2200U);
    assert(gs_ui_execute(&ui, &fixture.command, 2600U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_READER);
    fixture.generation = ui.generation;
    gs_test_clear(&fixture, 2800U);
    gs_test_emit(&fixture, GS_CLASS_FIST, 3600U);
    assert(gs_ui_execute(&ui, &fixture.command, 4000U) == GS_UI_APPLIED);
    assert(ui.mode == GS_UI_DIRECTORY);
    gs_test_clear(&fixture, 4200U);
    gs_test_emit(&fixture, GS_CLASS_POINT_RIGHT, 5000U);
    assert(gs_ui_local_action(&ui, GS_UI_ENTER, 5500U) == GS_UI_APPLIED);
    assert(gs_ui_execute(&ui, &fixture.command, 5501U) == GS_UI_REJECTED_STALE);
    gs_gesture_require_clear(&fixture.gesture);
    assert(fixture.gesture.state == GS_GESTURE_WAIT_CLEAR);
}

static void gs_test_swapped_directions_in_all_reader_modes(void)
{
    gs_fixture_t fixture;
    gs_ui_t ui;
    uint32_t start = 0U;
    unsigned mode;
    gs_test_init(&fixture);
    assert(gs_ui_init(&ui, gs_test_collections, 2U, 1000U));
    for (mode = 0U; mode < 3U; ++mode) {
        gs_test_clear(&fixture, start);
        gs_test_emit(&fixture, GS_CLASS_POINT_LEFT, start + 800U);
        assert(fixture.command.action == GS_UI_NEXT);
        assert(gs_ui_execute(&ui, &fixture.command, start + 1200U) == GS_UI_APPLIED);
        if (mode == 0U) { assert(ui.selected == 1U); }
        else if (mode == 1U) { assert(ui.chapter == 1U); }
        else { assert(ui.page == 1U); }
        fixture.generation = ui.generation;
        start += 1400U;
        gs_test_clear(&fixture, start);
        gs_test_emit(&fixture, GS_CLASS_POINT_RIGHT, start + 800U);
        assert(fixture.command.action == GS_UI_PREVIOUS);
        assert(gs_ui_execute(&ui, &fixture.command, start + 1200U) == GS_UI_APPLIED);
        if (mode == 0U) { assert(ui.selected == 0U); }
        else if (mode == 1U) { assert(ui.chapter == 0U); }
        else { assert(ui.page == 0U); }
        fixture.generation = ui.generation;
        start += 1400U;
        if (mode < 2U) {
            assert(gs_ui_local_action(&ui, GS_UI_ENTER, start) == GS_UI_APPLIED);
            fixture.generation = ui.generation;
        }
    }
}

static void gs_test_invalid_configuration(void)
{
    gs_gesture_t gesture;
    gs_ui_t ui;
    gs_gesture_config_t config = gs_gesture_default_config();
    config.candidate_ms = 0U;
    assert(!gs_gesture_init(&gesture, &config));
    assert(!gesture.initialized);
    assert(!gs_ui_init(&ui, NULL, 1U, 1000U));
    assert(!ui.initialized);
    assert(!gs_ui_init(&ui, gs_test_collections, 2U, 0U));
    assert(gs_ui_local_action(&ui, GS_UI_NEXT, 0U) == GS_UI_BAD_ARGUMENT);
}

int main(void)
{
    gs_test_startup_and_hold();
    gs_test_all_five_mappings();
    gs_test_minimum_frames_and_time();
    gs_test_deduplication_and_age();
    gs_test_age_boundary_and_future_recovery();
    gs_test_gap_timeout_and_recovery();
    gs_test_capture_gap_even_with_timely_delivery();
    gs_test_sequence_and_timestamp_faults();
    gs_test_rejection_and_class_change();
    gs_test_invalid_image_and_probabilities();
    gs_test_generation_and_enable();
    gs_test_uint32_wrap();
    gs_test_ui_navigation();
    gs_test_ui_command_revalidation();
    gs_test_full_flow_and_neutral_rearm();
    gs_test_swapped_directions_in_all_reader_modes();
    gs_test_invalid_configuration();
    puts("gesture/ui: 17 reader and gesture test groups passed");
    return 0;
}
