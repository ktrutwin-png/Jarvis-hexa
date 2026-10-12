package com.krakentrade.mobile

import java.util.UUID
import kotlin.math.min

data class AccountCapacity(
    val quoteBalance: Double,
    val baseBalance: Double,
    val accountEquityQuote: Double
)

data class StrategyConfig(
    val riskPct: Double = 0.5,
    val atrStopMultiplier: Double = 1.5,
    val rewardRiskRatio: Double = 2.0,
    val minStopPct: Double = 0.2,
    val maxVolume: Double = 1000.0
)

sealed interface ProposalDecision {
    data class Trade(val proposal: ExecutableProposal) : ProposalDecision
    data class Wait(val reason: String) : ProposalDecision
}

object ProposalEngine {
    fun build(
        pair: String,
        indicators: MarketIndicators,
        capacity: AccountCapacity,
        config: StrategyConfig = StrategyConfig(),
        proposalId: String = UUID.randomUUID().toString()
    ): ProposalDecision {
        require(config.riskPct > 0.0 && config.riskPct <= 1.0)
        require(config.rewardRiskRatio > 0.0)
        require(config.atrStopMultiplier > 0.0)
        require(config.minStopPct > 0.0)
        require(capacity.accountEquityQuote >= 0.0)

        if (indicators.lastClose <= 0.0 || indicators.atr <= 0.0) {
            return ProposalDecision.Wait("Brak wiarygodnej ceny lub ATR")
        }
        if (indicators.trend == Trend.FLAT) {
            return ProposalDecision.Wait("Brak jednoznacznego trendu")
        }

        val entry = indicators.lastClose
        val stopDistance = maxOf(
            indicators.atr * config.atrStopMultiplier,
            entry * (config.minStopPct / 100.0)
        )
        val riskBudget = capacity.accountEquityQuote * (config.riskPct / 100.0)
        if (riskBudget <= 0.0) return ProposalDecision.Wait("Brak budżetu ryzyka")

        val riskSizedVolume = riskBudget / stopDistance
        if (!riskSizedVolume.isFinite() || riskSizedVolume <= 0.0) {
            return ProposalDecision.Wait("Nieprawidłowy wolumen wynikający z ryzyka")
        }

        return when (indicators.trend) {
            Trend.UP -> {
                val affordableVolume = if (entry > 0.0) capacity.quoteBalance / entry else 0.0
                val volume = min(min(riskSizedVolume, affordableVolume), config.maxVolume)
                if (volume <= 0.0) {
                    ProposalDecision.Wait("Brak środków kwotowanych do zakupu")
                } else {
                    ProposalDecision.Trade(
                        ExecutableProposal(
                            id = proposalId,
                            pair = pair,
                            side = TradeSide.BUY,
                            entry = entry,
                            stopLoss = entry - stopDistance,
                            takeProfit = entry + stopDistance * config.rewardRiskRatio,
                            volume = volume,
                            maxRiskPct = config.riskPct
                        )
                    )
                }
            }

            Trend.DOWN -> {
                val volume = min(min(riskSizedVolume, capacity.baseBalance), config.maxVolume)
                if (volume <= 0.0) {
                    ProposalDecision.Wait("Brak aktywa bazowego do sprzedaży spot")
                } else {
                    ProposalDecision.Trade(
                        ExecutableProposal(
                            id = proposalId,
                            pair = pair,
                            side = TradeSide.SELL,
                            entry = entry,
                            stopLoss = entry + stopDistance,
                            takeProfit = entry - stopDistance * config.rewardRiskRatio,
                            volume = volume,
                            maxRiskPct = config.riskPct
                        )
                    )
                }
            }

            Trend.FLAT -> ProposalDecision.Wait("Brak jednoznacznego trendu")
        }
    }
}
