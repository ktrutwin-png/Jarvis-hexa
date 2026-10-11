package com.krakentrade.mobile

enum class TradeSide { BUY, SELL }

data class ExecutableProposal(
    val id: String,
    val pair: String,
    val side: TradeSide,
    val entry: Double,
    val stopLoss: Double,
    val takeProfit: Double,
    val volume: Double,
    val maxRiskPct: Double
)

data class RiskPolicy(
    val maxRiskPct: Double = 1.0,
    val maxVolume: Double = 1000.0
)

sealed interface ValidationResult {
    data object Valid : ValidationResult
    data class Invalid(val reason: String) : ValidationResult
}

object ProposalValidator {
    fun validate(p: ExecutableProposal, policy: RiskPolicy): ValidationResult {
        if (p.entry <= 0 || p.stopLoss <= 0 || p.takeProfit <= 0 || p.volume <= 0)
            return ValidationResult.Invalid("Parametry muszą być dodatnie")
        if (p.maxRiskPct <= 0 || p.maxRiskPct > policy.maxRiskPct)
            return ValidationResult.Invalid("Przekroczony limit ryzyka")
        if (p.volume > policy.maxVolume)
            return ValidationResult.Invalid("Przekroczony limit wolumenu")
        return when (p.side) {
            TradeSide.BUY -> if (p.stopLoss < p.entry && p.takeProfit > p.entry) ValidationResult.Valid
                else ValidationResult.Invalid("Nieprawidłowy SL/TP dla BUY")
            TradeSide.SELL -> if (p.stopLoss > p.entry && p.takeProfit < p.entry) ValidationResult.Valid
                else ValidationResult.Invalid("Nieprawidłowy SL/TP dla SELL")
        }
    }
}
