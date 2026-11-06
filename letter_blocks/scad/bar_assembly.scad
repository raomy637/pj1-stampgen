// bar_assembly.scad — 装配预览（只用于看图，不打印）
// 用法：openscad -o preview.png -D "cut=true" -D "cut_x=46" bar_assembly.scad

cut    = false;
cut_x  = 46;
show_letters = true;
show_cover   = true;

// 排一串字：A V I L O W，块宽 = advance，贴合摆放
letters = [
    ["A", 5.428, 0],
    ["V", 5.428, 5.428],
    ["I", 2.261, 10.856],
    ["L", 4.526, 13.117],
    ["O", 6.330, 17.643],
    ["W", 7.681, 23.973],
];

module body() {
    color([0.62, 0.66, 0.72])
        import("../out/07_bar/bar_base.stl", convexity = 6);
    if (show_cover)
        color([0.90, 0.58, 0.28])
            import("../out/07_bar/bar_cover.stl", convexity = 6);
    if (show_letters)
        for (i = [0:len(letters) - 1])
            color([0.20, 0.42, 0.62])
                translate([5 + letters[i][2], 0, 0])
                    import(str("../out/04_sample_t1.5_d14/", letters[i][0],
                               "_t1.5_d14.stl"), convexity = 6);
}

if (cut)
    difference() {
        body();
        translate([-200, -200, -200]) cube([cut_x + 200, 500, 500]);
    }
else
    body();
