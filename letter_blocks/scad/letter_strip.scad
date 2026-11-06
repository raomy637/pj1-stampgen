// letter_strip.scad — 把多个单字母块按真实字距排成一排，一次打印后掰开
//
// 用途：验证「块宽 = advance」能否复刻整块方案的字距。
// 块与块之间留 gap（默认 0.25mm）仅为切片可分，掰开后贴合拼装即恢复设计字距。
//
// 所有数组由 build.py 按字体度量算好传入，本文件不含任何字体假设。

letters   = is_undef(letters)   ? ["A"] : letters;
widths    = is_undef(widths)    ? [5.0] : widths;
xmins     = is_undef(xmins)     ? [0]   : xmins;
xmaxs     = is_undef(xmaxs)     ? [5.0] : xmaxs;
offsets   = is_undef(offsets)   ? [0]   : offsets;

block_depth     = is_undef(block_depth)     ? 13.0  : block_depth;
plate_thickness = is_undef(plate_thickness) ? 1.2   : plate_thickness;
letter_height   = is_undef(letter_height)   ? 6.0   : letter_height;
letter_size     = is_undef(letter_size)     ? 6.0   : letter_size;
baseline_y      = is_undef(baseline_y)      ? 0.317 : baseline_y;
font_family     = is_undef(font_family)     ? "Arial" : font_family;
font_style      = is_undef(font_style)      ? "Regular" : font_style;
overlap         = 0.05;

$fa = 4;
$fs = 0.3;

// 注意：这里不能再套一层 mirror。
// 每块内部已经镜像过字形（印章必需），若整体再 mirror 一次会抵消掉。
// 「顺序也要反」这件事由 build.py 传参时把字母序列倒过来实现：
// 要印 AVILOW，STL 里从左到右存成 W O L I V A（字形仍是反的），
// 压印翻转后纸上才是 A V I L O W 正读。
for (i = [0 : len(letters) - 1]) {
    translate([offsets[i], 0, 0]) {
        cube([widths[i], block_depth, plate_thickness]);
        translate([0, 0, plate_thickness - overlap])
            linear_extrude(height = letter_height + overlap)
                translate([xmins[i] + xmaxs[i], 0, 0])
                    mirror([1, 0, 0])
                        translate([0, baseline_y, 0])
                            text(letters[i],
                                 size   = letter_size,
                                 font   = str(font_family, ":style=", font_style),
                                 halign = "left",
                                 valign = "baseline");
    }
}
