// bar.scad — 排版长条（字粒夹持器）
//
// 结构：上下夹（base + cover），字粒被夹在中间
//   底板 base   两块托唇把字粒板托住，字从中间 8.2mm 的开口凸出
//   压盖 cover  从上方压住字粒板的顶面，6 颗 M3 拧紧
//
// 为什么不用「侧向螺杆顶紧」：
//   A→A / K→A / A→V 这些相邻对的墨迹间隙是负的（−0.15 ~ −0.10mm），
//   侧向大力挤压会让相邻字形互相顶住、把 A 的右腿压弯。
//   上下夹只压 Z 向，横向靠摩擦锁定，字距自然 = 各块 advance 之和，
//   和整块方案的印刷结果逐对一致。
//
// 为什么不用「端部装填」：
//   18 个字符从端面一个个塞进去要来回倒手；从上方放，摆错顺序一眼能看见、随手能改。
//
// 关键尺寸：
//   字粒板 14.0 × 1.5，凸出字高 6.0
//   开口 7.10mm（y 3.30~10.40）—— 由字形在 Y 向的真实范围决定：
//     普通字母 y 4.02~9.98，O/S/C/G 因 overshoot 到 10.09，
//     Q 的尾巴最低到 y=3.554（比基线低 0.46）—— 开口必须放过 Q，
//     否则 Q 会被托唇顶住坐不到底，整排基线就歪了。
//     取 3.30 起点，对 Q 留 0.25、对板前缘留 3.30 的托唇。
//   底板下沿离纸面 2.0mm（压印时托唇不沾墨）
//
// 坐标：X 沿长条，Y 沿字粒进深（y=0 是字粒板前缘），Z 向上（z=0 是印面）

part = 0;        // 0 = 底板，1 = 压盖

// ---- 排字区 ----
chan_len   = 145.0;   // 可用排字长度（18 个 W = 138.3，留 6.7 余量）
base_len   = 155.0;   // 底板总长 = chan_len + 2 × bridge
bridge     = 5.0;     // 两端挡墙（同时挡住字粒不许滑出）

// ---- Y 向 ----
plate_w    = 14.1;    // 字粒板 14.0 + 0.1 配合间隙
slot_y0    = 3.30;    // 字凸出开口的前沿
slot_w     = 7.10;    // 开口宽 —— 由 Q 的尾巴决定，见下
rail_f     = 9.30;    // 前轨宽（含螺丝位）
rail_b     = 9.80;    // 后轨宽
base_w     = rail_f + slot_w + rail_b;   // 26.2
cover_w    = 30.0;    // 压盖比底板宽 3.8，两侧各留 1.9 的盖沿
                      // —— 26.2 上放不下 φ6.2 沉头孔（字粒板占掉中间 14.1，
                      //    外侧只剩 6.0），加宽后沉头孔才不破边，顺便多个抠手边

// ---- Z 向 ----
clear      = 2.0;     // 底板下沿离纸面
plate_z    = 6.0;     // 字粒板底面（= 托唇顶面）
plate_t    = 1.5;     // 字粒板厚
base_t     = plate_z - clear;      // 4.0
cover_t    = 9.0;
cover_z    = plate_z + plate_t;    // 7.5 = 压盖下沿

// 挡墙只升到 7.0，比字粒板顶面低 0.5 —— 压盖只压在字粒上，
// 力才走得通「螺丝 → 压盖 → 字粒 → 托唇 → 底板 → 螺丝」这个闭环。
stop_h     = 1.0;

// ---- 螺丝 ----
screw_x    = [22, 77.5, 133];
screw_y    = [-3.0, 17.2];
pilot_d    = 2.7;     // M3 自攻导孔
clear_d    = 3.4;     // 压盖过孔
cbore_d    = 6.2;     // 沉头孔（M3 内六角头 φ5.5）
cbore_dp   = 3.2;

y0 = slot_y0 - rail_f;            // = -6.0（底板前缘）
cy0 = y0 - (cover_w - base_w) / 2;  // = -7.9（压盖前缘）

$fa = 4;
$fs = 0.4;

module base() {
    difference() {
        union() {
            translate([0, y0, clear]) cube([base_len, base_w, base_t]);
            translate([0, y0, plate_z]) cube([bridge, base_w, stop_h]);
            translate([base_len - bridge, y0, plate_z])
                cube([bridge, base_w, stop_h]);
        }
        // 字粒凸出槽（打穿底板）
        translate([bridge, slot_y0, clear - 0.1])
            cube([base_len - 2 * bridge, slot_w, base_t + 0.2]);
        // 螺丝导孔（打穿，M3×14 拧进去 3.5mm 不会露头）
        for (x = screw_x, y = screw_y)
            translate([x, y, clear - 0.1])
                cylinder(d = pilot_d, h = base_t + 0.2, $fn = 24);
    }
}

module cover() {
    difference() {
        translate([0, cy0, cover_z]) cube([base_len, cover_w, cover_t]);
        for (x = screw_x, y = screw_y) {
            translate([x, y, cover_z - 0.1])
                cylinder(d = clear_d, h = cover_t + 0.2, $fn = 24);
            translate([x, y, cover_z + cover_t - cbore_dp])
                cylinder(d = cbore_d, h = cbore_dp + 0.1, $fn = 32);
        }
    }
}

if (part == 0) base();
else cover();
