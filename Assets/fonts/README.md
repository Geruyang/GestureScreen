# Reader font

`NotoSansSC-VF.ttf` is a locally installed Noto Sans SC variable font used to
generate the reader's 24px and 32px, 4-bit anti-aliased glyph subsets. Its
SHA-256 is `763146584cf0710223441356b4395e279021b0806c196614377a7a0174ae074a`.
The font is distributed under the SIL Open Font License 1.1; the copyright and
full license are preserved in `OFL.txt`. The upstream project is
https://github.com/notofonts/noto-cjk and the license text is from
https://github.com/google/fonts/blob/main/ofl/notosanssc/OFL.txt.

`Tests/export_ui_font_aa.py` produces `Modules/Ui/Inc/gs_ui_font_aa_subset.h`.
The generated bitmap data is an embedded font derivative and must travel with
the OFL notice. The shipped UI does not load a font at runtime. The local font
file has not been byte-verified against a specific upstream release archive.
