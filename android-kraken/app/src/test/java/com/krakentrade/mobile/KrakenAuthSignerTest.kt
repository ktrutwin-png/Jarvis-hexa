package com.krakentrade.mobile

import org.junit.Assert.assertEquals
import org.junit.Test

class KrakenAuthSignerTest {
    @Test fun matchesKrakenOfficialSignatureExample() {
        val secret = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="
        val nonce = "1616492376594"
        val payload = "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25"
        val signature = KrakenAuthSigner.sign("/0/private/AddOrder", nonce, payload, secret)
        assertEquals(
            "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ==",
            signature
        )
    }
}
