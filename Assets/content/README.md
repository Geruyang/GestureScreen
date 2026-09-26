# 内置图文内容包

编辑 `package.json` 的目录、页面和可选图片，然后运行 `Tools/deploy_v5_content.py`。Python需要Pillow。默认输出 `Modules/Content/Src/gs_content_builtin.c`，编译并部署新的固件后生效。此方式不提供SD热插拔或外部Flash在线安装；不得把它记为外部存储验收通过。

格式版本1：1–8个目录，每目录1–32页，页面有title/body，可选相对image路径（PNG/JPEG）。单图不超过320×180，总计不超过16图、512KiB像素，UTF-8文本合计不超过32KiB；最终Flash容量还需构建确认。当前显示布局采用160×72示例。正文最多显示三行，v2示例按可见宽度编写，支持显式换行。文本受设备内置字体覆盖限制，示例用英文，非ASCII字符会记录到待字体检查清单。图片RGB888按r>>3、g>>2、b>>3转换为RGB565高字节在前，附IEEE CRC32。图片路径必须在包目录内；使用编码方向、不应用EXIF旋转，RGB转换丢弃alpha而不合成背景，只取首帧。图片请预先整理为所需方向及不透明RGB。

`gs_content_init`在任务启动前登记只读内容，StorageTask调用`gs_content_step`分片检查图片，每次最多4096字节。GUI只有在CRC通过后才能取图；未就绪或损坏时仍可显示页面文本。没有动态分配或擦写外部存储。

当前`roi.png`为本项目原创ROI示意图，可用`Tools/deploy_v5_content_assets.py`重新生成；不使用训练图像。编译器输出同名JSON记录Python/Pillow版本、源包及图片SHA256、像素CRC/SHA与生成C哈希。每个输出文件原子替换；两次替换之间中断时，构建校验应拒绝哈希不匹配的文件对。输出不得覆盖输入JSON或图片，重复JSON字段会被拒绝。

定向验证：`Tools/deploy_v5_content_check.py`覆盖合法CRC、分片预算、损坏回退、尺寸与字节数错误、空参数拒绝。替换包前保留旧JSON/图片以及冻结固件；回退使用已验证旧HEX，不能据文件名认定版本。
