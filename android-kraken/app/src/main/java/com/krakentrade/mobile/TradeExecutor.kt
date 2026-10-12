package com.krakentrade.mobile

interface KrakenPrivateApi {
    suspend fun placeEntryWithProtection(proposal: ExecutableProposal): Result<String>
}

class TradeExecutor(
    private val api: KrakenPrivateApi,
    private val gate: ApprovalGate,
    private val policy: RiskPolicy = RiskPolicy()
) {
    suspend fun execute(p: ExecutableProposal): Result<String> {
        val validation = ProposalValidator.validate(p, policy)
        if (validation is ValidationResult.Invalid)
            return Result.failure(IllegalArgumentException(validation.reason))
        if (!gate.consumeApproval(p.id))
            return Result.failure(SecurityException("Brak ręcznego zatwierdzenia"))
        return api.placeEntryWithProtection(p)
    }
}
