// letter_block.scad — 单字母印章块（活字字粒）
//
// 设计目标：与 stampgen 整块方案「逐字母复刻」，块宽严格等于字体 advance，
// 拼装后每一对相邻字母的墨迹间隙与整块方案完全一致。
//
// 坐标约定（与 stampgen 一致）：
//   X = 块宽（= advance，逐字母不同），Y = 块深（印章进深），Z = 底板厚度 + 字高
//   块占 [0, block_width] × [0, block_depth] × [0, plate_thickness]
//
// 镜像策略（关键）：
//   只镜像「字形」，不镜像「块」。若整块镜像，字母在块内的左右留白会互换，
//   块宽 = advance 时字距就会错。这里做法是：字形绕 x=0 翻转后，再平移
//   (ink_xmin + ink_xmax)，使其墨迹仍落在 [ink_xmin, ink_xmax]。
//   结果：字形是反的（印章需要），但占位与整块方案完全相同。
//
// 基线策略（关键）：
//   所有字母共用一条基线（baseline_y），以「大写字高 cap 的中心」对齐块深中心。
//   不能按每个字母自己的墨迹包围盒居中 —— O/S/C 有 overshoot、Q 有尾巴，
//   各自居中会导致拼起来高低不齐。

letter          = "A";
block_width     = 5.428;
block_depth     = 13.0;
plate_thickness = 1.2;
letter_height   = 6.0;
letter_size     = 6.0;
ink_xmin        = -0.012;
ink_xmax        = 5.570;
baseline_y      = 0.317;
font_family     = "Arial";
font_style      = "Regular";
overlap         = 0.05;

$fa = 4;
$fs = 0.3;

module glyph2d() {
    translate([ink_xmin + ink_xmax, 0, 0])
        mirror([1, 0, 0])
            translate([0, baseline_y, 0])
                text(letter,
                     size   = letter_size,
                     font   = str(font_family, ":style=", font_style),
                     halign = "left",
                     valign = "baseline");
}

module block() {
    cube([block_width, block_depth, plate_thickness]);
    translate([0, 0, plate_thickness - overlap])
        linear_extrude(height = letter_height + overlap)
            glyph2d();
}

block();
