package com.krakentrade.mobile

import java.util.concurrent.atomic.AtomicLong

class KrakenNonce(
    initialValue: Long = System.currentTimeMillis()
) {
    private val last = AtomicLong(initialValue)

    fun next(): String {
        while (true) {
            val previous = last.get()
            val now = System.currentTimeMillis()
            val candidate = maxOf(now, previous + 1)
            if (last.compareAndSet(previous, candidate)) return candidate.toString()
        }
    }
}
