package com.krakentrade.mobile

enum class ExecutionMode {
    VALIDATE_ONLY,
    LIVE
}

/**
 * Production adapter behind TradeExecutor.
 *
 * VALIDATE_ONLY is the default mode and cannot create a real order.
 * LIVE first asks Kraken to validate the exact protected entry and only then
 * submits the same entry with a conditional stop-loss.
 */
class KrakenTradeExecutionApi(
    private val bracket: BracketExecutionCoordinator,
    private val mode: ExecutionMode = ExecutionMode.VALIDATE_ONLY
) : KrakenPrivateApi {
    override suspend fun placeEntryWithProtection(
        proposal: ExecutableProposal
    ): Result<String> {
        val preflight = bracket.preflight(proposal)
        preflight.exceptionOrNull()?.let { return Result.failure(it) }

        if (mode == ExecutionMode.VALIDATE_ONLY) {
            return Result.success("validated:" + proposal.id)
        }
        return bracket.placeEntry(proposal)
    }
}
