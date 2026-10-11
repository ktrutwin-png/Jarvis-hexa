package com.krakentrade.mobile

import org.junit.Assert.*
import org.junit.Test

class ApprovalGateTest {
    @Test fun approvalIsSingleUse() {
        val gate = ApprovalGate()
        gate.approve("abc")
        assertTrue(gate.consumeApproval("abc"))
        assertFalse(gate.consumeApproval("abc"))
    }

    @Test fun unknownProposalIsRejected() {
        assertFalse(ApprovalGate().consumeApproval("missing"))
    }
}
