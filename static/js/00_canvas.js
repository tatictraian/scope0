// --- 00_canvas.js ---
// Reactive canvas background adapted from web-construct.ro
// Sparse pixel grid, island formations, cursor glitch field, spark particles, scanlines
// Cursor glitch field (0x0E) ported from web-construct.ro source

(function() {
    'use strict';

    const canvas = document.getElementById('bgCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    // --- Configuration ---
    const BG_COLOR = '#040704';
    const CELL = 6;
    const PIXEL_DENSITY = 0.04;
    const SCANLINE_ALPHA = 0.007;
    const SCANLINE_STEP = 3;
    const MAX_SPARKS = 80;
    const MAX_TAGS = 30;

    // --- State ---
    let W = 0, H = 0;
    let mouseX = 0, mouseY = 0;
    let lastMx = 0, lastMy = 0;
    let mouseSpeed = 0, mouseEnergy = 0;
    let pixels = [];
    let sparks = [];
    let exposureTags = [];
    let panelRects = [];
    let frameCount = 0;
    let t = 0;
    let glitchActive = false, glitchTimer = 0;

    // --- Resize with DPR ---
    function resize() {
        W = window.innerWidth;
        H = window.innerHeight;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        generatePixels();
        updatePanelRects();
    }

    // --- Pixel grid generation ---
    function generatePixels() {
        pixels = [];
        for (let x = 0; x < W; x += CELL) {
            for (let y = 0; y < H; y += CELL) {
                if (Math.random() < PIXEL_DENSITY) {
                    pixels.push({
                        x: x, y: y,
                        ox: x, oy: y,
                        vx: 0, vy: 0,
                        phase: Math.random() * Math.PI * 2,
                        baseSpeed: 0.08 + Math.random() * 0.2,
                        baseBright: 0.01 + Math.random() * 0.025,
                    });
                }
            }
        }
    }

    // --- Island detection: find panel bounding rects ---
    function updatePanelRects() {
        panelRects = [];
        const panels = document.querySelectorAll('.panel');
        panels.forEach(function(p) {
            const r = p.getBoundingClientRect();
            const pad = 30;
            panelRects.push({
                x1: r.left - pad, y1: r.top - pad,
                x2: r.right + pad, y2: r.bottom + pad,
                pad: pad,
            });
        });
    }

    // --- Check if point is inside a panel island ---
    function getIslandInfo(px, py) {
        for (let i = 0; i < panelRects.length; i++) {
            const r = panelRects[i];
            if (px >= r.x1 && px <= r.x2 && py >= r.y1 && py <= r.y2) {
                const edgeDist = Math.min(px - r.x1, r.x2 - px, py - r.y1, r.y2 - py);
                return { inside: true, solidity: Math.min(1, edgeDist / r.pad) };
            }
        }
        return { inside: false, solidity: 0 };
    }

    // --- Panel proximity for glow ---
    function panelProximity(px, py) {
        let minDist = Infinity;
        for (let i = 0; i < panelRects.length; i++) {
            const r = panelRects[i];
            const cx = Math.max(r.x1, Math.min(px, r.x2));
            const cy = Math.max(r.y1, Math.min(py, r.y2));
            const dx = px - cx, dy = py - cy;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < minDist) minDist = dist;
        }
        return minDist;
    }

    // --- Spark particles ---
    function spawnSpark(x, y, intense) {
        if (sparks.length >= MAX_SPARKS) return;
        sparks.push({
            x: x, y: y,
            vx: (Math.random() - 0.5) * (intense ? 3 : 1.5),
            vy: (Math.random() - 0.5) * (intense ? 3 : 1.5),
            life: 1.0,
            decay: 0.006 + Math.random() * 0.015,
            size: 1 + Math.random() * (intense ? 3 : 2),
            bright: intense || Math.random() < 0.25,
        });
    }

    // --- Exposure tags (populated externally) ---
    window.addExposureTag = function(text, severity) {
        if (exposureTags.length >= MAX_TAGS) exposureTags.shift();
        exposureTags.push({
            text: text,
            severity: severity || 'INFO',
            x: 50 + Math.random() * (W - 100),
            y: 50 + Math.random() * (H - 100),
            ox: 0, oy: 0,
            vx: 0, vy: 0,
            alpha: 0,
            targetAlpha: severity === 'CRITICAL' ? 0.4 : severity === 'WARNING' ? 0.3 : 0.2,
            phase: Math.random() * Math.PI * 2,
            driftSpeed: 0.1 + Math.random() * 0.3,
            driftAmp: 15 + Math.random() * 20,
        });
    };

    // --- Glitch burst (triggered externally) ---
    window.triggerGlitchBurst = function(intensity) {
        glitchActive = true;
        glitchTimer = 0.1 + (intensity || 0.5) * 0.2;
        mouseEnergy = Math.min(1, mouseEnergy + (intensity || 0.5));
    };

    // --- Score reveal burst (triggered externally) ---
    window.triggerScoreBurst = function(x, y) {
        for (let i = 0; i < 20; i++) {
            const angle = (Math.PI * 2 * i) / 20;
            spawnSpark(x + Math.cos(angle) * 30, y + Math.sin(angle) * 30, true);
        }
    };

    // --- Mouse + touch tracking ---
    document.addEventListener('mousemove', function(e) {
        mouseX = e.clientX; mouseY = e.clientY;
        mouseSpeed = Math.sqrt(Math.pow(mouseX - lastMx, 2) + Math.pow(mouseY - lastMy, 2));
        lastMx = mouseX; lastMy = mouseY;
    });
    document.addEventListener('touchmove', function(e) {
        if (e.touches.length > 0) {
            mouseX = e.touches[0].clientX; mouseY = e.touches[0].clientY;
            mouseSpeed = Math.sqrt(Math.pow(mouseX - lastMx, 2) + Math.pow(mouseY - lastMy, 2));
            lastMx = mouseX; lastMy = mouseY;
        }
    }, { passive: true });
    document.addEventListener('mouseleave', function() { mouseEnergy = 0; mouseSpeed = 0; });

    // --- Dashboard visibility: reduce work when panels cover the canvas ---
    let dashboardVisible = false;
    window.setCanvasDashboardMode = function(visible) {
        dashboardVisible = visible;
    };

    // --- Main render loop ---
    function render() {
        t += 0.016;
        frameCount++;

        // Skip every other frame when dashboard is visible (panels cover most canvas)
        if (dashboardVisible && frameCount % 2 === 0) {
            requestAnimationFrame(render);
            return;
        }

        // Mouse energy — quadratic, smooth (from web-construct.ro)
        const targetEnergy = Math.min(1, mouseSpeed / 30);
        if (targetEnergy > mouseEnergy) mouseEnergy += (targetEnergy - mouseEnergy) * 0.12;
        else mouseEnergy *= 0.97;
        if (mouseEnergy < 0.001) mouseEnergy = 0;

        // Glitch on fast movement
        if (mouseSpeed > 15 && Math.random() < 0.15) {
            glitchActive = true; glitchTimer = 0.03 + Math.random() * 0.1;
        }
        if (glitchActive) { glitchTimer -= 0.016; if (glitchTimer <= 0) glitchActive = false; }

        // Clear
        ctx.fillStyle = BG_COLOR;
        ctx.fillRect(0, 0, W, H);

        // Update panel rects periodically
        if (frameCount % 60 === 0) updatePanelRects();

        // --- Ambient glow ---
        const amb = 0.006 + mouseEnergy * 0.015;
        const g1 = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) * 0.45);
        g1.addColorStop(0, 'rgba(0,255,0,' + (amb + Math.sin(t * 0.4) * 0.003) + ')');
        g1.addColorStop(1, 'transparent');
        ctx.fillStyle = g1; ctx.fillRect(0, 0, W, H);

        // --- Mouse glow ---
        if (mouseEnergy > 0.01) {
            const mg = ctx.createRadialGradient(mouseX, mouseY, 0, mouseX, mouseY, 200 + mouseEnergy * 150);
            mg.addColorStop(0, 'rgba(0,255,0,' + (mouseEnergy * 0.04) + ')');
            mg.addColorStop(0.5, 'rgba(0,255,0,' + (mouseEnergy * 0.015) + ')');
            mg.addColorStop(1, 'transparent');
            ctx.fillStyle = mg; ctx.fillRect(0, 0, W, H);
        }

        // --- Scanlines ---
        ctx.fillStyle = 'rgba(0,255,0,' + SCANLINE_ALPHA + ')';
        for (let sl = 0; sl < H; sl += SCANLINE_STEP) ctx.fillRect(0, sl, W, 1);

        // --- Exposure tags (adapted from web-construct.ro 0x0A) ---
        ctx.font = '10px Courier New';
        ctx.textBaseline = 'middle';
        for (let ti = 0; ti < exposureTags.length; ti++) {
            const tg = exposureTags[ti];

            // Drift
            const driftX = Math.sin(t * tg.driftSpeed + tg.phase) * tg.driftAmp;
            const driftY = Math.cos(t * tg.driftSpeed * 0.7 + tg.phase * 1.3) * tg.driftAmp * 0.6;
            tg.ox = tg.x + driftX;
            tg.oy = tg.y + driftY;

            // Fade in
            if (tg.alpha < tg.targetAlpha) tg.alpha = Math.min(tg.alpha + 0.005, tg.targetAlpha);

            // Wrap
            if (tg.ox < -100) tg.ox = W + 50;
            if (tg.ox > W + 100) tg.ox = -50;

            // Mouse proximity vibration
            const tdx = tg.ox - mouseX, tdy = tg.oy - mouseY;
            const tDist = Math.sqrt(tdx * tdx + tdy * tdy);
            const tInfluence = Math.max(0, 1 - tDist / 300) * mouseEnergy;

            if (tInfluence > 0.01) {
                tg.vx += (Math.random() - 0.5) * tInfluence * 3;
                tg.vy += (Math.random() - 0.5) * tInfluence * 3;
            }
            tg.vx *= 0.88; tg.vy *= 0.88;

            let tBright = tg.alpha + tInfluence * 0.15;
            if (glitchActive && Math.random() < 0.2) tBright += 0.1;
            tBright *= (0.7 + Math.sin(t * tg.driftSpeed * 2 + tg.phase) * 0.3);

            if (tBright > 0.01) {
                const c = tg.severity === 'CRITICAL' ? '239,68,68'
                         : tg.severity === 'WARNING' ? '245,158,11'
                         : '56,189,248';
                ctx.fillStyle = 'rgba(' + c + ',' + Math.min(0.4, tBright).toFixed(3) + ')';
                ctx.fillText(tg.text, (tg.ox + tg.vx) | 0, (tg.oy + tg.vy) | 0);
                // Glow halo on bright tags
                if (tBright > 0.06) {
                    ctx.fillStyle = 'rgba(' + c + ',' + (tBright * 0.2).toFixed(3) + ')';
                    ctx.fillText(tg.text, (tg.ox + tg.vx + 0.5) | 0, (tg.oy + tg.vy + 0.5) | 0);
                }
            }
        }

        // --- Background pixels (from web-construct.ro 0x0B) ---
        for (let i = 0; i < pixels.length; i++) {
            const p = pixels[i];
            const dmx = p.ox - mouseX, dmy = p.oy - mouseY;
            const mDist = Math.sqrt(dmx * dmx + dmy * dmy);
            const mInf = Math.max(0, 1 - mDist / 350) * mouseEnergy;

            if (mInf > 0.01) {
                p.vx += (Math.random() - 0.5) * mInf * 2;
                p.vy += (Math.random() - 0.5) * mInf * 2;
            }
            p.vx += (p.ox - p.x) * 0.1; p.vy += (p.oy - p.y) * 0.1;
            p.vx *= 0.85; p.vy *= 0.85;
            p.x += p.vx; p.y += p.vy;

            const shimmer = Math.sin(t * p.baseSpeed + p.phase) * 0.5 + 0.5;
            let bright = p.baseBright * shimmer + mInf * 0.12;
            if (glitchActive && Math.random() < 0.3) {
                bright += 0.08;
                p.x += Math.floor(Math.random() * 3 - 1) * CELL;
            }

            // Island proximity boost
            const panelDist = panelProximity(p.ox, p.oy);
            if (panelDist < 60) {
                const edgeFactor = 1 - panelDist / 60;
                const frag = Math.sin(p.ox * 0.1 + p.oy * 0.13 + t) * 0.5 + 0.5;
                bright += edgeFactor * frag * 0.08;
            }

            if (bright > 0.005) {
                ctx.fillStyle = 'rgba(0,255,0,' + Math.min(0.3, bright).toFixed(3) + ')';
                ctx.fillRect(p.x | 0, p.y | 0, CELL - 1, CELL - 1);
                if (bright > 0.04) {
                    ctx.fillStyle = 'rgba(0,255,0,' + (bright * 0.2).toFixed(3) + ')';
                    ctx.fillRect((p.x - 1) | 0, (p.y - 1) | 0, CELL + 2, CELL + 2);
                }
            }
        }

        // --- Cursor glitch field (from web-construct.ro 0x0E) ---
        if (mouseEnergy > 0.02) {
            const glitchRadius = 40 + mouseEnergy * 60;
            const glitchCells = Math.ceil(glitchRadius * 2 / CELL);
            const startCol = Math.floor((mouseX - glitchRadius) / CELL);
            const startRow = Math.floor((mouseY - glitchRadius) / CELL);
            const glitchIntensity = mouseEnergy * mouseEnergy; // quadratic

            for (let gr = 0; gr < glitchCells; gr++) {
                for (let gc = 0; gc < glitchCells; gc++) {
                    const gpx = (startCol + gc) * CELL;
                    const gpy = (startRow + gr) * CELL;
                    const gdx = gpx + CELL / 2 - mouseX, gdy = gpy + CELL / 2 - mouseY;
                    const gDist = Math.sqrt(gdx * gdx + gdy * gdy);

                    if (gDist > glitchRadius) continue;
                    let gFalloff = 1 - gDist / glitchRadius;
                    gFalloff *= gFalloff; // squared falloff

                    if (Math.random() > gFalloff * 0.7 + 0.1) continue;

                    const gType = Math.random();
                    if (gType < 0.35) {
                        // Bright green pixel flash
                        ctx.fillStyle = 'rgba(0,255,0,' + (gFalloff * glitchIntensity * 0.25).toFixed(3) + ')';
                        ctx.fillRect(gpx, gpy, CELL - 0.5, CELL - 0.5);
                    } else if (gType < 0.55) {
                        // Displaced pixel
                        const shiftX = Math.floor(Math.random() * 5 - 2) * CELL;
                        const shiftY = Math.floor(Math.random() * 3 - 1) * CELL;
                        ctx.fillStyle = 'rgba(0,255,0,' + (gFalloff * glitchIntensity * 0.15).toFixed(3) + ')';
                        ctx.fillRect(gpx + shiftX, gpy + shiftY, CELL - 0.5, CELL - 0.5);
                    } else if (gType < 0.7) {
                        // Horizontal scan line tear
                        const tearLen = CELL * (3 + Math.floor(Math.random() * 6));
                        ctx.fillStyle = 'rgba(0,255,0,' + (gFalloff * glitchIntensity * 0.12).toFixed(3) + ')';
                        ctx.fillRect(gpx - tearLen / 2, gpy, tearLen, 1);
                    } else if (gType < 0.85) {
                        // Dark void hole with green edge
                        ctx.fillStyle = 'rgba(4,7,4,' + (gFalloff * 0.8).toFixed(3) + ')';
                        ctx.fillRect(gpx, gpy, CELL, CELL);
                        ctx.fillStyle = 'rgba(0,255,0,' + (gFalloff * glitchIntensity * 0.08).toFixed(3) + ')';
                        ctx.fillRect(gpx, gpy, CELL, 0.5);
                    } else {
                        // Bright spark dot
                        ctx.beginPath();
                        ctx.arc(gpx + CELL / 2, gpy + CELL / 2, 1 + gFalloff * 2, 0, Math.PI * 2);
                        ctx.fillStyle = 'rgba(0,255,0,' + (gFalloff * glitchIntensity * 0.5).toFixed(3) + ')';
                        ctx.fill();
                    }
                }
            }
        }

        // --- Sparks (from web-construct.ro 0x0D) ---
        if (Math.random() < (0.03 + mouseEnergy * 0.15))
            spawnSpark(mouseX + (Math.random() - 0.5) * 200, mouseY + (Math.random() - 0.5) * 200, mouseEnergy > 0.5);

        // Sparks near panel edges
        if (frameCount % 3 === 0 && panelRects.length > 0) {
            const r = panelRects[Math.random() * panelRects.length | 0];
            if (r) {
                const side = Math.random() * 4 | 0;
                let sx, sy;
                if (side === 0) { sx = r.x1 + Math.random() * (r.x2 - r.x1); sy = r.y1; }
                else if (side === 1) { sx = r.x2; sy = r.y1 + Math.random() * (r.y2 - r.y1); }
                else if (side === 2) { sx = r.x1 + Math.random() * (r.x2 - r.x1); sy = r.y2; }
                else { sx = r.x1; sy = r.y1 + Math.random() * (r.y2 - r.y1); }
                spawnSpark(sx, sy, false);
            }
        }

        for (let si = sparks.length - 1; si >= 0; si--) {
            const s = sparks[si];
            s.x += s.vx; s.y += s.vy; s.life -= s.decay;
            if (s.life <= 0) { sparks.splice(si, 1); continue; }
            ctx.beginPath(); ctx.arc(s.x, s.y, s.size * s.life, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(0,255,0,' + (s.life * (s.bright ? 0.6 : 0.3)).toFixed(3) + ')';
            ctx.fill();
            if (s.bright && s.life > 0.5) {
                ctx.beginPath(); ctx.arc(s.x, s.y, s.size * s.life * 3.5, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(0,255,0,' + (s.life * 0.05).toFixed(3) + ')';
                ctx.fill();
            }
        }

        requestAnimationFrame(render);
    }

    // --- Init ---
    window.addEventListener('resize', resize);
    resize();
    requestAnimationFrame(render);
})();
