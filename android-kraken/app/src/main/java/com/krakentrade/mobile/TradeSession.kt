package com.krakentrade.mobile

class TradeSession(
    private val executor: TradeExecutor,
    private val gate: ApprovalGate
) {
    var state: TradeState = TradeState.Idle
        private set

    fun present(proposal: ExecutableProposal) {
        state = TradeState.AwaitingApproval(proposal)
    }

    fun reject() {
        val current = state
        if (current is TradeState.AwaitingApproval) {
            state = TradeState.Rejected(current.proposal.id)
        }
    }

    suspend fun approveAndExecute(): Result<String> {
        val current = state
        if (current !is TradeState.AwaitingApproval) {
            return Result.failure(IllegalStateException("Brak propozycji oczekującej na zatwierdzenie"))
        }

        val proposal = current.proposal
        gate.approve(proposal.id)
        state = TradeState.Submitting(proposal.id)

        return executor.execute(proposal)
            .onSuccess { orderId -> state = TradeState.ProtectedOpen(orderId) }
            .onFailure { error -> state = TradeState.Failed(error.message ?: "Nieznany błąd") }
    }
}
