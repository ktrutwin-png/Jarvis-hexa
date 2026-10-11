package com.krakentrade.mobile

import java.math.BigDecimal
import java.math.RoundingMode

data class NormalizedProposal(
    val proposal: ExecutableProposal,
    val pairId: String,
    val entry: String,
    val stopLoss: String,
    val takeProfit: String,
    val volume: String
)

object PairOrderRules {
    fun normalize(
        proposal: ExecutableProposal,
        rules: PairRules
    ): Result<NormalizedProposal> = runCatching {
        require(rules.isOnline) { "Para " + rules.displayName + " nie jest online" }

        val entry = roundPrice(proposal.entry, rules)
        val stop = roundPrice(proposal.stopLoss, rules)
        val takeProfit = roundPrice(proposal.takeProfit, rules)
        val volume = roundVolume(proposal.volume, rules)

        require(volume.toDouble() >= rules.orderMin) {
            "Wolumen poniżej minimum " + rules.orderMin
        }
        require(entry.toDouble() * volume.toDouble() >= rules.costMin) {
            "Wartość zlecenia poniżej minimum " + rules.costMin
        }

        val normalizedProposal = proposal.copy(
            entry = entry.toDouble(),
            stopLoss = stop.toDouble(),
            takeProfit = takeProfit.toDouble(),
            volume = volume.toDouble()
        )
        val validation = ProposalValidator.validate(normalizedProposal, RiskPolicy())
        require(validation is ValidationResult.Valid) {
            (validation as ValidationResult.Invalid).reason
        }

        NormalizedProposal(
            proposal = normalizedProposal,
            pairId = rules.altName,
            entry = entry.toPlainString(),
            stopLoss = stop.toPlainString(),
            takeProfit = takeProfit.toPlainString(),
            volume = volume.toPlainString()
        )
    }

    private fun roundPrice(value: Double, rules: PairRules): BigDecimal {
        require(value > 0.0)
        val raw = BigDecimal.valueOf(value)
        val tick = BigDecimal.valueOf(rules.tickSize)
        if (rules.tickSize > 0.0) {
            val ticks = raw.divide(tick, 0, RoundingMode.HALF_UP)
            return ticks.multiply(tick).setScale(rules.pairDecimals, RoundingMode.HALF_UP)
        }
        return raw.setScale(rules.pairDecimals, RoundingMode.HALF_UP)
    }

    private fun roundVolume(value: Double, rules: PairRules): BigDecimal {
        require(value > 0.0)
        return BigDecimal.valueOf(value)
            .setScale(rules.lotDecimals, RoundingMode.DOWN)
            .stripTrailingZeros()
    }
}
