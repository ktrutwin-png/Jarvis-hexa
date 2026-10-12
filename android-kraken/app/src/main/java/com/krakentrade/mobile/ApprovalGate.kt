package com.krakentrade.mobile

class ApprovalGate {
    private val approved = mutableSetOf<String>()

    @Synchronized fun approve(proposalId: String) { approved.add(proposalId) }

    @Synchronized fun consumeApproval(proposalId: String): Boolean =
        approved.remove(proposalId)
}
