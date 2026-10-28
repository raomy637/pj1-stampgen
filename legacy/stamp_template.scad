// ===== 参数设置 =====
name          = "BELLA";   // 默认印章文字（会被命令行覆盖）
base_len      = 36;        // 底座长度，会被 -D base_len=xx 覆盖
base_width    = 6;         // 底座宽度 (Y)
base_height   = 10;        // 底座高度 (Z)

letter_size   = 6;         // 字体高度 (size)
letter_height = 6;         // 文字挤出高度
font_name     = "Arial";   // 字体

$fn = 64;                  // 圆弧精细度（可选）

// 文字底面往底座里多埋一点点。
// 原来是严丝合缝贴在 z=base_height/2 上，两个面完全共面，
// CGAL 做并集时要反复切分共面面片，单个名字会从 3 秒拖到 13 秒。
// 往下埋 0.05mm（打印精度以下，肉眼和成品都看不出来）后共面消失，
// 并集恢复正常速度，顺带保证模型是连通的、不会出现悬空文字。
overlap = 0.05;

// ===== 主体模块 =====
module stamp_body() {
    union() {
        // 底座：居中放置
        cube([base_len, base_width, base_height], center = true);

        // 文字：放在底座顶面，向上拉伸（底部下沉 overlap 保证与底座相交）
        translate([0, 0, base_height/2 - overlap])
            linear_extrude(height = letter_height + overlap)
                text(name,
                     size   = letter_size,
                     font   = font_name,
                     halign = "center",
                     valign = "center");
    }
}

// ===== 镜像整个印章（压印后文字为正） =====
mirror([1, 0, 0])   // 沿 YZ 平面左右翻转
    stamp_body();
