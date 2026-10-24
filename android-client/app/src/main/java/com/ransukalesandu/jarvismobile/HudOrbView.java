package com.ransukalesandu.jarvismobile;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.os.SystemClock;
import android.util.AttributeSet;
import android.view.View;

/** Small native animated orb; it draws locally on the tablet and needs no remote assets. */
public final class HudOrbView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private volatile boolean active = false;
    private volatile float level = 0.0f;

    public HudOrbView(Context context) {
        super(context);
        setLayerType(View.LAYER_TYPE_HARDWARE, null);
    }

    public HudOrbView(Context context, AttributeSet attrs) {
        super(context, attrs);
        setLayerType(View.LAYER_TYPE_HARDWARE, null);
    }

    public void setActive(boolean value) {
        active = value;
        invalidate();
    }

    public void setLevel(float value) {
        level = Math.max(0.0f, Math.min(1.0f, value));
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float cx = getWidth() / 2.0f;
        float cy = getHeight() / 2.0f;
        float base = Math.min(getWidth(), getHeight()) * 0.27f;
        float t = SystemClock.uptimeMillis() / 450.0f;
        float energy = active ? (0.18f + level * 0.72f) : 0.10f;
        float pulse = (float) (Math.sin(t) * 0.5 + 0.5);
        float core = base * (0.88f + 0.07f * pulse + 0.08f * level);

        paint.setShader(new RadialGradient(cx, cy, base * 2.2f,
                new int[]{Color.argb(active ? 84 : 35, 34, 214, 255),
                        Color.argb(28, 15, 107, 170), Color.TRANSPARENT},
                null, Shader.TileMode.CLAMP));
        paint.setStyle(Paint.Style.FILL);
        canvas.drawCircle(cx, cy, base * 2.2f, paint);
        paint.setShader(null);

        for (int i = 0; i < 5; i++) {
            float phase = t * (0.55f + i * 0.11f) + i * 0.92f;
            float drift = (float) (Math.sin(phase) * base * (0.045f + energy * 0.05f));
            float radius = base * (0.88f + i * 0.18f + drift / base);
            int alpha = Math.max(26, Math.min(190, (int) ((active ? 112 : 70) - i * 12 + level * 50)));
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(i == 0 ? 2.3f : 1.1f);
            paint.setColor(Color.argb(alpha, 92, 242, 255));
            canvas.drawCircle(cx, cy, radius, paint);
        }

        paint.setStyle(Paint.Style.FILL);
        paint.setShader(new RadialGradient(cx - core * 0.20f, cy - core * 0.22f, core * 1.55f,
                new int[]{Color.rgb(180, 255, 255), Color.rgb(24, 174, 222),
                        Color.rgb(8, 42, 76), Color.rgb(4, 13, 26)},
                new float[]{0.0f, 0.28f, 0.72f, 1.0f}, Shader.TileMode.CLAMP));
        canvas.drawCircle(cx, cy, core, paint);
        paint.setShader(null);

        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(2.0f);
        paint.setColor(Color.argb(active ? 235 : 135, 92, 242, 255));
        canvas.drawCircle(cx, cy, core * 1.12f, paint);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.argb(active ? 230 : 125, 218, 252, 255));
        canvas.drawCircle(cx, cy, Math.max(3.0f, core * (0.055f + level * 0.035f)), paint);

        paint.setStrokeWidth(1.0f);
        paint.setColor(Color.argb(active ? 115 : 55, 92, 242, 255));
        float outer = base * 1.95f;
        for (int i = 0; i < 8; i++) {
            double angle = (Math.PI * 2.0 * i / 8.0) + t * 0.15;
            float x1 = cx + (float) Math.cos(angle) * outer * 0.90f;
            float y1 = cy + (float) Math.sin(angle) * outer * 0.90f;
            float x2 = cx + (float) Math.cos(angle) * outer;
            float y2 = cy + (float) Math.sin(angle) * outer;
            canvas.drawLine(x1, y1, x2, y2, paint);
        }
        postInvalidateDelayed(40L);
    }
}
