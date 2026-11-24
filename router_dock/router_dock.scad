// =============================================================
// router_dock.scad  -  Parametric vertical-slot router dock
// Draft v0.6 / units: mm
// Axes: X = slot row direction, Y = slot length, Z = height
// v0.2: SOLID base -> no bridges, no isolated islands, no stringing
// v0.3: + upright fence slats (modes 1/2, superseded)
// v0.4: independent posts, 4 per slot, front/back open;
//       lead-in chamfer only at the Y ends -> zero unsupported faces
// v0.5: slot width +1 mm along X only; separate-key joint coupons
// v0.6: INTEGRAL male/female joint - LEFT end = female T pocket,
//       RIGHT end = male T tenon. No separate key any more.
//       Tenon length is counted INSIDE the 249 mm envelope so the
//       module still fits the P1S 256 mm bed with 7 mm to spare.
// v0.7: UNIFORM PITCH. The seam clear gap equals M_L + M_R and is
//       INDEPENDENT of GAP, so set M_L + M_R = GAP to make the seam as
//       wide as every internal channel. GAP 25 -> 22, margins 8/2 -> 11/11:
//       envelope stays 249 mm, seam 10 -> 22 mm, and the last slot's right
//       posts regain their full 5 mm (right wall 2 -> 11 mm).
// =============================================================

$fn = 16;

// ---- Print mode ----------------------------------------------
SOLID = 1;   // 1 = solid blind slots (default); 0 = legacy grated + feet
VENT  = 0;   // 1 = solid + standoff pads + open end notches (still no bridges)

// ---- Fence posts (v0.4: independent posts) -------------------
FENCE_ON   = 1;
FENCE_MODE = 3;    // 3 = independent posts, 4 per slot  <-- current design
FENCE_T    = 5;    // post thickness (sketch: 0.5 cm = 5 mm)
FENCE_H    = 25;   // post height ABOVE the slot rim plane (sketch: 2.5 cm)
FENCE_L    = 18;   // post length along the slot (~1/4 of slot length)
FENCE_END  = 3;    // gap from the post outer end to the slot end

// ---- Router / slot (UNCONFIRMED, tune after fit test) --------
SLOT_L      = 70;
SLOT_W      = 25;
SLOT_W_ADD  = 1;     // v0.5: widen the slot by 1 mm along X ONLY
CLEARANCE   = 0.3;   // per-side fit clearance (FDM inner walls shrink)
SLOT_DEPTH  = 10;    // insertion depth; hard max 10 (fan intake)
ROUTER_SHOW = 50;    // exposed height used only by the preview mock-up

// ---- Base ----------------------------------------------------
BASE_T       = 5;    // solid floor thickness (sketch: 0.5 cm)
FOOT_H       = 5;    // legacy only
GAP          = 22;   // v0.7: clear gap between slots. Equals M_L + M_R so
                     // the seam is exactly as wide as an internal channel.
                     // Was 25; reducing it keeps the envelope at 249 mm.
N_SLOTS      = 5;
END_MARGIN   = 11;   // LEFT margin, hosts the 6 mm deep female pocket.
                     // Must stay >= T_DEPTH + 2 or the pocket cuts slot 1.
END_MARGIN_R = 11;   // RIGHT margin behind the male tenon. Must stay >=
                     // FENCE_T (5) or the last slot's right posts get clipped
                     // by the body outline (v0.6 had 2 mm -> thin 2 mm posts).
Y_MARGIN     = 5;
CORNER_R     = 2;
CHAMFER      = 1;

// ---- Integral male/female joint (v0.6) -----------------------
// T-shape locks the modules against being pulled apart along X.
// JOINT_LOCK = 0 switches to a plain rectangular tenon, which can be
// pushed in horizontally but has NO mechanical lock (friction only).
JOINT_LOCK = 1;
T_DEPTH    = 6;      // pocket depth / tenon reach
T_NECK_X   = 2;      // narrow mouth length along X
T_NECK_W   = 6;      // narrow mouth width along Y
T_HEAD_W   = 12;     // wide pocket width along Y
JOINT_GAP  = 0.3;    // per-side clearance of the printed male tenon
// NOTE: the female pocket runs all the way down to z=0. A bottom stop
// ledge would force the tenon to start at z=1 and create a downward
// facing unsupported face. Both modules sit flat on the desk instead.

// ---- Joint fit-test coupon -----------------------------------
JT_X = 10;           // 6 mm pocket/tenon + 4 mm backing wall
JT_Y = 28;           // 12 mm joint + 8 mm wall on each side
JT_GAP_Y = 5;        // spacing between the two coupons in one STL

// ---- VENT option (additive pads + open notches, no bridges) --
PAD_H    = 2;
PAD_W    = 4;
NOTCH_W  = 10;

// ---- Derived (do not edit) -----------------------------------
SW      = SLOT_W + SLOT_W_ADD + 2*CLEARANCE;                  // 26.6
SL      = SLOT_L + 2*CLEARANCE;                               // 70.6
PITCH   = SW + GAP;                                           // 48.6
SLOTS_W = N_SLOTS*SW + (N_SLOTS-1)*GAP;                      // 221
SEAM    = END_MARGIN + END_MARGIN_R;                          // 22 == GAP
BODY_W  = END_MARGIN + SLOTS_W + END_MARGIN_R;                // 243
MW      = BODY_W + T_DEPTH;                                   // 249 incl. tenon
MD      = 2*Y_MARGIN + SL;                                    // 80.6
ZBASE   = SOLID == 1 ? 0 : FOOT_H;
ZB      = ZBASE + BASE_T;                                     // 5
ZT      = ZB + SLOT_DEPTH;                                    // 15
ZF      = ZT + (FENCE_ON == 1 ? FENCE_H : 0);                 // 40
CY      = MD/2;
V0W     = 2*END_MARGIN + SW + GAP;                            // 70.6

// 1 = V0 coupon, 2 = full module (default),
// 4 = fit-test coupon pair, 5 = assembled joint demo.
// PART_ID 3 (separate key) was retired in v0.6.
PART_ID = 2;

// ---- 2D rounded rectangle, extruded --------------------------
module rr(w, d, r) {
    q = min(r, min(w, d)/2 - 0.01);
    hull() {
        translate([q,     q])     circle(q);
        translate([w - q, q])     circle(q);
        translate([q,     d - q]) circle(q);
        translate([w - q, d - q]) circle(q);
    }
}

module rr_box(w, d, h, r) {
    linear_extrude(height = h, convexity = 6) rr(w, d, r);
}

// ---- Slot cavity + lead-in chamfer ---------------------------
module slot_cut(x) {
    translate([x, Y_MARGIN, ZB])
        rr_box(SW, SL, SLOT_DEPTH + 0.2, CORNER_R);
    // Lead-in bevel only at the FRONT / BACK ends of the slot (Y).
    // Widening it along X would cut 1 mm into the posts at z=ZT and
    // leave each post with an unsupported horizontal lip.
    hull() {
        translate([x, Y_MARGIN, ZT - CHAMFER])
            rr_box(SW, SL, 0.01, CORNER_R);
        translate([x, Y_MARGIN - CHAMFER, ZT + 0.01])
            cube([SW, SL + 2*CHAMFER, 0.01]);
    }
}

// ---- Legacy only ---------------------------------------------
module grid_holes(x) {
    for (j = [0:2])
        translate([x + 3 + j*7.5, Y_MARGIN + 5, ZBASE - 0.1])
            rr_box(4, SL - 10, BASE_T + 0.4, 1.2);
}

module vented_rails(W) {
    seg = 20; notch = 8;
    for (x = [0 : seg + notch : W]) {
        w = min(seg, W - x);
        if (w > 2) {
            translate([x, 0, 0])     rr_box(w, 5, FOOT_H + 0.1, 1);
            translate([x, MD-5, 0])  rr_box(w, 5, FOOT_H + 0.1, 1);
        }
    }
}

// ---- Upright fence posts -------------------------------------
module fence_post(W, n, x0) {
    for (i = [0 : n-1]) {
        x = x0 + i*PITCH;
        for (y = [Y_MARGIN + FENCE_END,
                  Y_MARGIN + SL - FENCE_END - FENCE_L]) {
            // Start at the slot FLOOR: a post starting at ZT would have a
            // 1 mm unsupported lip above the mouth chamfer.
            translate([x - FENCE_T, y, ZB])
                cube([FENCE_T, FENCE_L, ZT - ZB + FENCE_H]);
            translate([x + SW, y, ZB])
                cube([FENCE_T, FENCE_L, ZT - ZB + FENCE_H]);
        }
    }
}

module fence(W, n, x0) {
    if (FENCE_ON == 1)
        intersection() {
            translate([0, 0, ZB])
                linear_extrude(height = ZT - ZB + FENCE_H, convexity = 6)
                    rr(W, MD, 3);
            union() {
                if (FENCE_MODE == 3) fence_post(W, n, x0);
            }
        }
}

// ---- Female T pocket at the LEFT end face --------------------
// Through Z = 0 .. ZT. No floor ledge (see NOTE above).
module female_pocket(yc = CY) {
    h = ZT + 0.4;
    if (JOINT_LOCK == 1) {
        translate([-0.2, yc - T_NECK_W/2, -0.2])
            cube([T_NECK_X + 0.2, T_NECK_W, h]);
        translate([T_NECK_X, yc - T_HEAD_W/2, -0.2])
            cube([T_DEPTH - T_NECK_X, T_HEAD_W, h]);
    } else {
        translate([-0.2, yc - T_HEAD_W/2, -0.2])
            cube([T_DEPTH + 0.2, T_HEAD_W, h]);
    }
}

// ---- Male T tenon growing from the RIGHT end face ------------
// X = BODY_W .. BODY_W + (T_DEPTH - JOINT_GAP), Z = 0 .. ZT.
// Every layer is attached to the body at X = BODY_W, so there is no
// overhang; no supports and no separate part are needed.
module male_tenon(x0 = BODY_W, yc = CY) {
    g  = JOINT_GAP;
    nw = T_NECK_W - 2*g;    // 5.4
    hw = T_HEAD_W - 2*g;    // 11.4
    L  = T_DEPTH - g;       // 5.7
    if (JOINT_LOCK == 1) {
        translate([x0, yc - nw/2, 0])
            cube([T_NECK_X, nw, ZT]);
        translate([x0 + T_NECK_X, yc - hw/2, 0])
            cube([L - T_NECK_X, hw, ZT]);
    } else {
        translate([x0, yc - hw/2, 0])
            cube([L, hw, ZT]);
    }
}

// ---- VENT option ---------------------------------------------
module standoff_pads(x) {
    for (px = [x + 1.5, x + SW - 1.5 - PAD_W])
        for (py = [Y_MARGIN + 1.5, Y_MARGIN + SL - 1.5 - PAD_W])
            translate([px, py, ZB])
                rr_box(PAD_W, PAD_W, PAD_H, 0.6);
}

module end_notches(x) {
    nx = x + (SW - NOTCH_W)/2;
    translate([nx, -0.2, ZB])
        cube([NOTCH_W, Y_MARGIN + 1.2, SLOT_DEPTH + 0.2]);
    translate([nx, Y_MARGIN + SL - 1.0, ZB])
        cube([NOTCH_W, Y_MARGIN + 1.2, SLOT_DEPTH + 0.2]);
}

// ---- Body: solid block + fence, all connected ----------------
module body(W, n, x0) {
    union() {
        if (SOLID == 1)
            rr_box(W, MD, ZT, 3);
        else
            union() {
                translate([0, 0, ZBASE]) rr_box(W, MD, ZT - ZBASE, 3);
                vented_rails(W);
            }
        fence(W, n, x0);
    }
}

module cuts(W, n, x0) {
    for (i = [0 : n-1]) {
        x = x0 + i*PITCH;
        slot_cut(x);
        if (SOLID == 0) grid_holes(x);
        if (SOLID == 1 && VENT == 1) end_notches(x);
    }
}

module pads_for(n, x0) {
    if (SOLID == 1 && VENT == 1)
        for (i = [0 : n-1]) standoff_pads(x0 + i*PITCH);
}

// ---- Full 5-slot module: female LEFT + male RIGHT ------------
module full_module() {
    union() {
        difference() {
            body(BODY_W, N_SLOTS, END_MARGIN);
            cuts(BODY_W, N_SLOTS, END_MARGIN);
            female_pocket();
        }
        male_tenon();
        pads_for(N_SLOTS, END_MARGIN);
    }
}

// ---- V0 fit-test coupon: no joint, symmetric margins --------
module v0_test() {
    union() {
        difference() {
            body(V0W, 1, END_MARGIN);
            cuts(V0W, 1, END_MARGIN);
        }
        pads_for(1, END_MARGIN);
    }
}

// ---- Minimal joint fit-test: ONE print yields both pieces ----
// Female coupon: pocket opens toward -X. Male coupon: tenon points +X.
// Put them on the plate side by side; after printing, lift the male
// piece, line the tenon up over the pocket and let it drop in.
module joint_coupon_female() {
    h = ZT + 0.4;
    difference() {
        cube([JT_X, JT_Y, ZT]);
        female_pocket(JT_Y/2);
    }
}

module joint_coupon_male() {
    union() {
        cube([JT_X, JT_Y, ZT]);
        male_tenon(JT_X, JT_Y/2);
    }
}

module joint_fit_test() {
    joint_coupon_female();
    translate([0, JT_Y + JT_GAP_Y, 0]) joint_coupon_male();
}

// Preview-only: fully seated assembly. X is exactly aligned, because a T
// tenon CANNOT be pushed in along X (its wide head would hit the narrow
// mouth); it is dropped in along Z instead. Lifting the demo piece would
// create a fake downward-facing face at the lift height, so the demo stays
// seated and every printed face still rests on z=0. Both solids are the
// same as in joint_fit_test, only relocated -> volumes must add up exactly.
// NOT a printable part.
module joint_pair_demo() {
    translate([-JT_X, 0, 0]) joint_coupon_male();
    joint_coupon_female();
}

// ---- Entry point ---------------------------------------------
if (PART_ID == 1)          v0_test();
else if (PART_ID == 4)     joint_fit_test();
else if (PART_ID == 5)     joint_pair_demo();
else                       full_module();
