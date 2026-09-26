/**
  ******************************************************************************
  * @file    gs_network.h
  * @date    2026-09-22T17:46:54+0800
  * @brief   ST.AI Tool Automatic Code Generator for Embedded NN computing
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
#ifndef STAI_GS_NETWORK_DETAILS_H
#define STAI_GS_NETWORK_DETAILS_H

#include "stai.h"
#include "layers.h"

const stai_network_details g_gs_network_details = {
  .tensors = (const stai_tensor[45]) {
   { .size_bytes = 27648, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 96, 96, 3}}, .scale = {1, (const float[1]){1.0}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "serving_default_rgb960_output" },
   { .size_bytes = 27648, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 96, 96, 3}}, .scale = {1, (const float[1]){0.0117647061124444}}, .zeropoint = {1, (const int16_t[1]){-43}}, .name = "eltwise_0_output" },
   { .size_bytes = 27649, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 96, 96, 3}}, .scale = {1, (const float[1]){0.007843137718737125}}, .zeropoint = {1, (const int16_t[1]){-1}}, .name = "eltwise_1_output" },
   { .size_bytes = 20000, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 8, 48, 48}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_2_output" },
   { .size_bytes = 20000, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 8, 50, 50}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_3_pad_before_output" },
   { .size_bytes = 18432, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 48, 48, 8}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_3_output" },
   { .size_bytes = 40000, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 16, 48, 48}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_4_output" },
   { .size_bytes = 40000, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 16, 50, 50}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_5_pad_before_output" },
   { .size_bytes = 9216, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 24, 24, 16}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_5_output" },
   { .size_bytes = 21632, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 32, 24, 24}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_6_output" },
   { .size_bytes = 21632, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 32, 26, 26}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_7_pad_before_output" },
   { .size_bytes = 18432, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 24, 24, 32}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_7_output" },
   { .size_bytes = 21632, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 32, 24, 24}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_8_output" },
   { .size_bytes = 21632, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 32, 26, 26}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_9_pad_before_output" },
   { .size_bytes = 4608, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 12, 12, 32}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_9_output" },
   { .size_bytes = 12544, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 64, 12, 12}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_10_output" },
   { .size_bytes = 12544, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 64, 14, 14}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_11_pad_before_output" },
   { .size_bytes = 9216, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 12, 12, 64}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_11_output" },
   { .size_bytes = 12544, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 64, 12, 12}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_12_output" },
   { .size_bytes = 12544, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 64, 14, 14}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_13_pad_before_output" },
   { .size_bytes = 2304, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 6, 6, 64}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_13_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 6, 6}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_14_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 8, 8}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_15_pad_before_output" },
   { .size_bytes = 4608, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 6, 6, 128}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_15_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 6, 6}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_16_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 8, 8}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_17_pad_before_output" },
   { .size_bytes = 4608, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 6, 6, 128}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_17_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 6, 6}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_18_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 8, 8}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_19_pad_before_output" },
   { .size_bytes = 4608, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 6, 6, 128}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_19_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 6, 6}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_20_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 8, 8}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_21_pad_before_output" },
   { .size_bytes = 4608, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 6, 6, 128}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_21_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 6, 6}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_22_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 8, 8}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_23_pad_before_output" },
   { .size_bytes = 4608, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 6, 6, 128}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_23_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 6, 6}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_24_output" },
   { .size_bytes = 8192, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_FIRST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 128, 8, 8}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_25_pad_before_output" },
   { .size_bytes = 1152, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 3, 3, 128}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_25_output" },
   { .size_bytes = 2304, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 3, 3, 256}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_26_output" },
   { .size_bytes = 6400, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 5, 5, 256}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_27_pad_before_output" },
   { .size_bytes = 2304, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 3, 3, 256}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_27_output" },
   { .size_bytes = 2304, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 3, 3, 256}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "conv2d_28_output" },
   { .size_bytes = 256, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {4, (const int32_t[4]){1, 1, 1, 256}}, .scale = {1, (const float[1]){0.0235294122248888}}, .zeropoint = {1, (const int16_t[1]){-128}}, .name = "pool_29_output" },
   { .size_bytes = 6, .flags = (STAI_FLAG_HAS_BATCH|STAI_FLAG_CHANNEL_LAST), .format = STAI_FORMAT_S8, .shape = {2, (const int32_t[2]){1, 6}}, .scale = {1, (const float[1]){0.09457084536552429}}, .zeropoint = {1, (const int16_t[1]){-31}}, .name = "gemm_30_output" }
  },
  .nodes = (const stai_node_details[44]){
    {.id = 0, .type = AI_LAYER_ELTWISE_INTEGER_TYPE, .input_tensors = {1, (const int32_t[1]){0}}, .output_tensors = {1, (const int32_t[1]){1}} }, /* eltwise_0 */
    {.id = 1, .type = AI_LAYER_ELTWISE_INTEGER_TYPE, .input_tensors = {1, (const int32_t[1]){1}}, .output_tensors = {1, (const int32_t[1]){2}} }, /* eltwise_1 */
    {.id = 2, .type = AI_LAYER_OPTIMIZED_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){2}}, .output_tensors = {1, (const int32_t[1]){3}} }, /* conv2d_2 */
    {.id = 3, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){3}}, .output_tensors = {1, (const int32_t[1]){4}} }, /* conv2d_3_pad_before */
    {.id = 3, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){4}}, .output_tensors = {1, (const int32_t[1]){5}} }, /* conv2d_3 */
    {.id = 4, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){5}}, .output_tensors = {1, (const int32_t[1]){6}} }, /* conv2d_4 */
    {.id = 5, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){6}}, .output_tensors = {1, (const int32_t[1]){7}} }, /* conv2d_5_pad_before */
    {.id = 5, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){7}}, .output_tensors = {1, (const int32_t[1]){8}} }, /* conv2d_5 */
    {.id = 6, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){8}}, .output_tensors = {1, (const int32_t[1]){9}} }, /* conv2d_6 */
    {.id = 7, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){9}}, .output_tensors = {1, (const int32_t[1]){10}} }, /* conv2d_7_pad_before */
    {.id = 7, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){10}}, .output_tensors = {1, (const int32_t[1]){11}} }, /* conv2d_7 */
    {.id = 8, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){11}}, .output_tensors = {1, (const int32_t[1]){12}} }, /* conv2d_8 */
    {.id = 9, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){12}}, .output_tensors = {1, (const int32_t[1]){13}} }, /* conv2d_9_pad_before */
    {.id = 9, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){13}}, .output_tensors = {1, (const int32_t[1]){14}} }, /* conv2d_9 */
    {.id = 10, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){14}}, .output_tensors = {1, (const int32_t[1]){15}} }, /* conv2d_10 */
    {.id = 11, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){15}}, .output_tensors = {1, (const int32_t[1]){16}} }, /* conv2d_11_pad_before */
    {.id = 11, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){16}}, .output_tensors = {1, (const int32_t[1]){17}} }, /* conv2d_11 */
    {.id = 12, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){17}}, .output_tensors = {1, (const int32_t[1]){18}} }, /* conv2d_12 */
    {.id = 13, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){18}}, .output_tensors = {1, (const int32_t[1]){19}} }, /* conv2d_13_pad_before */
    {.id = 13, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){19}}, .output_tensors = {1, (const int32_t[1]){20}} }, /* conv2d_13 */
    {.id = 14, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){20}}, .output_tensors = {1, (const int32_t[1]){21}} }, /* conv2d_14 */
    {.id = 15, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){21}}, .output_tensors = {1, (const int32_t[1]){22}} }, /* conv2d_15_pad_before */
    {.id = 15, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){22}}, .output_tensors = {1, (const int32_t[1]){23}} }, /* conv2d_15 */
    {.id = 16, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){23}}, .output_tensors = {1, (const int32_t[1]){24}} }, /* conv2d_16 */
    {.id = 17, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){24}}, .output_tensors = {1, (const int32_t[1]){25}} }, /* conv2d_17_pad_before */
    {.id = 17, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){25}}, .output_tensors = {1, (const int32_t[1]){26}} }, /* conv2d_17 */
    {.id = 18, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){26}}, .output_tensors = {1, (const int32_t[1]){27}} }, /* conv2d_18 */
    {.id = 19, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){27}}, .output_tensors = {1, (const int32_t[1]){28}} }, /* conv2d_19_pad_before */
    {.id = 19, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){28}}, .output_tensors = {1, (const int32_t[1]){29}} }, /* conv2d_19 */
    {.id = 20, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){29}}, .output_tensors = {1, (const int32_t[1]){30}} }, /* conv2d_20 */
    {.id = 21, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){30}}, .output_tensors = {1, (const int32_t[1]){31}} }, /* conv2d_21_pad_before */
    {.id = 21, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){31}}, .output_tensors = {1, (const int32_t[1]){32}} }, /* conv2d_21 */
    {.id = 22, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){32}}, .output_tensors = {1, (const int32_t[1]){33}} }, /* conv2d_22 */
    {.id = 23, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){33}}, .output_tensors = {1, (const int32_t[1]){34}} }, /* conv2d_23_pad_before */
    {.id = 23, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){34}}, .output_tensors = {1, (const int32_t[1]){35}} }, /* conv2d_23 */
    {.id = 24, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){35}}, .output_tensors = {1, (const int32_t[1]){36}} }, /* conv2d_24 */
    {.id = 25, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){36}}, .output_tensors = {1, (const int32_t[1]){37}} }, /* conv2d_25_pad_before */
    {.id = 25, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){37}}, .output_tensors = {1, (const int32_t[1]){38}} }, /* conv2d_25 */
    {.id = 26, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){38}}, .output_tensors = {1, (const int32_t[1]){39}} }, /* conv2d_26 */
    {.id = 27, .type = AI_LAYER_PAD_TYPE, .input_tensors = {1, (const int32_t[1]){39}}, .output_tensors = {1, (const int32_t[1]){40}} }, /* conv2d_27_pad_before */
    {.id = 27, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){40}}, .output_tensors = {1, (const int32_t[1]){41}} }, /* conv2d_27 */
    {.id = 28, .type = AI_LAYER_CONV2D_TYPE, .input_tensors = {1, (const int32_t[1]){41}}, .output_tensors = {1, (const int32_t[1]){42}} }, /* conv2d_28 */
    {.id = 29, .type = AI_LAYER_POOL_TYPE, .input_tensors = {1, (const int32_t[1]){42}}, .output_tensors = {1, (const int32_t[1]){43}} }, /* pool_29 */
    {.id = 30, .type = AI_LAYER_DENSE_TYPE, .input_tensors = {1, (const int32_t[1]){43}}, .output_tensors = {1, (const int32_t[1]){44}} } /* gemm_30 */
  },
  .n_nodes = 44
};
#endif

