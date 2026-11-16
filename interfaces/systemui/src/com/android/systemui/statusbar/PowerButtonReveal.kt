/*
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
// Device-owned extraction of PowerButtonReveal from SystemUI/statusbar/LightRevealScrim.kt.
// Upstream: LineageOS android_frameworks_base, 696a5773fa284f53429dbb6c3e5dcc96bf5bd0b3.
package com.android.systemui.statusbar

import com.android.app.animation.Interpolators
import com.android.systemui.sheng.ShengPowerButtonGeometry
import com.android.systemui.statusbar.LightRevealEffect.Companion.getPercentPastThreshold

data class PowerButtonReveal(
    /** Approximate Y-value of the center of the button in the display's native orientation. */
    val powerButtonY: Float
) : LightRevealEffect {

    /** Start the original reveal oval just outside the physical button's edge. */
    private val OFF_SCREEN_START_AMOUNT = 0.05f

    private val INCREASE_MULTIPLIER = 1.25f

    override fun setRevealAmountOnScrim(amount: Float, scrim: LightRevealScrim) {
        val interpolatedAmount = Interpolators.FAST_OUT_SLOW_IN_REVERSE.getInterpolation(amount)
        val fadeAmount = getPercentPastThreshold(interpolatedAmount, 0.5f)

        with(scrim) {
            revealGradientEndColorAlpha = 1f - fadeAmount
            interpolatedRevealAmount = interpolatedAmount
            val position = ShengPowerButtonGeometry.position(
                context,
                width.toFloat(),
                height.toFloat(),
                powerButtonY,
                OFF_SCREEN_START_AMOUNT,
            )
            val horizontalRadius =
                width * (if (position.isOnVerticalEdge()) INCREASE_MULTIPLIER else 1f) *
                    interpolatedAmount
            val verticalRadius =
                height * (if (position.isOnVerticalEdge()) 1f else INCREASE_MULTIPLIER) *
                    interpolatedAmount
            setRevealGradientBounds(
                position.x - horizontalRadius,
                position.y - verticalRadius,
                position.x + horizontalRadius,
                position.y + verticalRadius,
            )
        }
    }
}
