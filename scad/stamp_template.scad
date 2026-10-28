// stamp_template.scad — 参数化名字印章模板
//
// 设计要点：
//   1. 所有参数用 is_undef 三元式声明，既可被命令行 -D 覆盖，
//      也可直接在 OpenSCAD 中打开预览（此时取默认值）。
//   2. 文字与底座留 0.05mm 重叠，避免共面产生非流形边。
//   3. 整体沿 YZ 平面镜像，压印后文字为正读。
//   4. $fa/$fs 取代 $fn，按弦高控制曲面精度，避免字母曲面过度细分。

name           = is_undef(name)           ? "BELLA"   : name;
base_len       = is_undef(base_len)       ? 30        : base_len;
base_width     = is_undef(base_width)     ? 6         : base_width;
base_height    = is_undef(base_height)    ? 10        : base_height;
letter_size    = is_undef(letter_size)    ? 5.5       : letter_size;
letter_spacing = is_undef(letter_spacing) ? 1.0       : letter_spacing;
letter_height  = is_undef(letter_height)  ? 6         : letter_height;
font_family    = is_undef(font_family)    ? "Arial"   : font_family;
font_style     = is_undef(font_style)     ? "Regular" : font_style;
weight_offset  = is_undef(weight_offset)  ? 0         : weight_offset;
// outline_fix > 0 时先对字形做一次极小的圆角外扩，用来修复自交轮廓。
// 某些字母（如 Daziji 系列的小写 y）轮廓有重复点或自交，单独挤出看不出问题，
// 但和底座做 union 时 CGAL 会报 "mesh is not closed" 并退化成只有底座。
// offset(r=0.001) 会重建多边形，0.001mm 的尺寸影响可以忽略。
outline_fix    = is_undef(outline_fix)    ? 0         : outline_fix;
text_offset_y  = is_undef(text_offset_y)  ? 0         : text_offset_y;
curve_fa       = is_undef(curve_fa)       ? 4         : curve_fa;
curve_fs       = is_undef(curve_fs)       ? 0.4       : curve_fs;

$fa = curve_fa;
$fs = curve_fs;

overlap = 0.05;

module glyphs_2d() {
    // valign="baseline" 让文字基线落在 y=0，
    // 再由 text_offset_y 把「大写字高带」的中心移到原点，
    // 这样换任何字体都能保持光学居中。
    translate([0, text_offset_y, 0])
        text(name,
             size    = letter_size,
             font    = str(font_family, ":style=", font_style),
             spacing = letter_spacing,
             halign  = "center",
             valign  = "baseline");
}

module glyphs_fixed_2d() {
    if (outline_fix > 0)
        offset(r = outline_fix) glyphs_2d();
    else
        glyphs_2d();
}

module glyphs_weighted_2d() {
    if (weight_offset > 0.001)
        offset(delta = weight_offset) glyphs_fixed_2d();
    else
        glyphs_fixed_2d();
}

module stamp_body() {
    union() {
        cube([base_len, base_width, base_height], center = true);
        translate([0, 0, base_height / 2 - overlap])
            linear_extrude(height = letter_height + overlap)
                glyphs_weighted_2d();
    }
}

mirror([1, 0, 0]) stamp_body();
