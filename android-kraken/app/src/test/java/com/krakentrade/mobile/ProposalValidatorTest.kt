package com.krakentrade.mobile

import org.junit.Assert.*
import org.junit.Test

class ProposalValidatorTest {
    @Test fun validBuyPasses() {
        val p = ExecutableProposal("1","XRP/EUR",TradeSide.BUY,2.0,1.9,2.2,100.0,0.5)
        assertEquals(ValidationResult.Valid, ProposalValidator.validate(p, RiskPolicy()))
    }

    @Test fun invalidProtectionFails() {
        val p = ExecutableProposal("1","XRP/EUR",TradeSide.BUY,2.0,2.1,2.2,100.0,0.5)
        assertTrue(ProposalValidator.validate(p, RiskPolicy()) is ValidationResult.Invalid)
    }

    @Test fun excessiveRiskFails() {
        val p = ExecutableProposal("1","XRP/EUR",TradeSide.BUY,2.0,1.9,2.2,100.0,2.0)
        assertTrue(ProposalValidator.validate(p, RiskPolicy(maxRiskPct=1.0)) is ValidationResult.Invalid)
    }
}
