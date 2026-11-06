// tray.scad — 字粒收纳盘（长方形 / 分区 / 每格刻字符）
//
// 用途：放 185 件字粒（26 字母 ×5 + I 额外 5 + 10 数字 ×5）。
//
// 分区：
//   前 2 行 = 数字区 0-9 + 2 个空位
//   后 5 行 = 字母区 A-Z + 4 个空位
//   两区之间用 2.4mm 厚的隔墙分开（普通隔墙 1.2mm），手一摸就知道分界在哪
//
// 每格：
//   格内 37 × 20mm（第 5 列 43mm，专给 W 的 5 件：5×7.681+4×0.5 = 40.4mm）
//   格底前缘留 6mm 空档，刻 4mm 高的字符 —— 字粒推到最里侧，字符不会被挡住
//   字符凹刻 0.8mm，格底 2.0mm 还剩 1.2mm，不影响强度；0.8 深在实物上有明显阴影
//
// 高度：
//   底板 2.0 + 壁高 9.0 = 11.0mm
//   字粒高 7.5mm（板 1.5 + 字 6.0），坐进格底后比盘沿低 1.5mm
//   → 不加盖也不会掉出来，将来要加盖也正好有 1.5mm 的台阶
//
// 坐标：
//   X 向右，Y 向里（-Y 是使用者站的这一侧 / 正面），Z 向上
//   文字在格底以 +Y 为「上」，站在 -Y 侧看是正读的
//
// 分件（打印台面放不下时用）：
//   part = 0 整件 238 × 152.4
//   part = 1 左半（第 1~3 列）  part = 2 右半（第 4~6 列）
//   切缝落在第 3、4 列之间的隔墙里，两侧各自收口成完整外墙，拼起来严丝合缝

rows            = 7;
cols            = 6;
cell_w          = 37.0;
cell_w_wide     = 43.0;
wide_col        = 4;
cell_d          = 20.0;
floor_t         = 2.0;
wall_h          = 9.0;
wall_out        = 2.0;
wall_in         = 1.2;
wall_sect       = 2.4;
sect_after_row  = 1;
corner_r        = 3.0;
cell_r          = 1.2;

part            = 0;
split_col       = 3;

labels          = [""];
label_cap       = 4.0;
label_size      = 4.0235;
label_depth     = 0.8;
label_off       = 3.0;

font_family     = "Arial";
font_style      = "Regular";

$fa = 4;
$fs = 0.4;

function col_w(c) = (c == wide_col) ? cell_w_wide : cell_w;

function acc_x(c) = (c <= 0) ? wall_out : acc_x(c - 1) + col_w(c - 1) + wall_in;

function gap_after(r) = (r == sect_after_row) ? wall_sect : wall_in;

function acc_y(r) = (r <= 0) ? wall_out : acc_y(r - 1) + cell_d + gap_after(r - 1);

function full_x() = acc_x(cols - 1) + col_w(cols - 1) + wall_out;
function full_y() = acc_y(rows - 1) + cell_d + wall_out;

function c_lo() = (part == 2) ? split_col : 0;
function c_hi() = (part == 1) ? split_col - 1 : cols - 1;

function x_start() = (part == 2) ? acc_x(split_col) - wall_out : 0;

function body_x() = (part == 1)
    ? acc_x(split_col - 1) + col_w(split_col - 1) + wall_out
    : (part == 2) ? full_x() - x_start() : full_x();

module rrect2d(w, d, r) {
    offset(r = r) offset(r = -r) square([w, d]);
}

module body() {
    linear_extrude(height = floor_t + wall_h)
        rrect2d(body_x(), full_y(), corner_r);
}

module pockets() {
    for (r = [0:rows - 1], c = [c_lo():c_hi()])
        translate([acc_x(c) - x_start(), acc_y(r)])
            translate([0, 0, floor_t])
                linear_extrude(height = wall_h + 1)
                    rrect2d(col_w(c), cell_d, cell_r);
}

module labels_cut() {
    for (r = [0:rows - 1], c = [c_lo():c_hi()])
        if (labels[r * cols + c] != "")
            translate([acc_x(c) - x_start() + col_w(c) / 2,
                       acc_y(r) + label_off - label_cap / 2,
                       floor_t - label_depth])
                linear_extrude(height = label_depth + 0.01)
                    text(labels[r * cols + c],
                         size   = label_size,
                         font   = str(font_family, ":style=", font_style),
                         halign = "center",
                         valign = "baseline");
}

difference() {
    body();
    pockets();
    labels_cut();
}
