package com.krakentrade.mobile

sealed interface TradeState {
    data object Idle : TradeState
    data class AwaitingApproval(val proposal: ExecutableProposal) : TradeState
    data class Submitting(val proposalId: String) : TradeState
    data class ProtectedOpen(val orderId: String) : TradeState
    data class Rejected(val proposalId: String) : TradeState
    data class Failed(val message: String) : TradeState
}
