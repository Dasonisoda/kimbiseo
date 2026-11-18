package kr.kimbiseo.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RulesTest {
    private val fp = "3F2A91C0" + "0".repeat(48) + "ABCDEF12"

    @Test fun parsePairUrl() {
        val u = "kimbiseo://pair?v=1&h=192.168.1.23%2C100.101.1.2&p=8874&c=12345678&f=$fp&n=%EA%B1%B0%EC%8B%A4%20PC"
        val p = PairRules.parse(u)
        assertNotNull(p)
        assertEquals(listOf("192.168.1.23", "100.101.1.2"), p!!.hosts)
        assertEquals(8874, p.port); assertEquals("12345678", p.code); assertEquals(fp, p.fp); assertEquals("거실 PC", p.pcName)
    }

    @Test fun rejectBadPair() {
        assertNull(PairRules.parse("https://evil.example/pair?v=1"))
        assertNull(PairRules.parse("kimbiseo://pair?v=2&h=192.168.1.23&p=8874&c=12345678&f=$fp"))
        assertNull(PairRules.parse("kimbiseo://pair?v=1&h=8.8.8.8&p=8874&c=12345678&f=$fp"))          // 공인 주소
        assertNull(PairRules.parse("kimbiseo://pair?v=1&h=example.com&p=8874&c=12345678&f=$fp"))       // 이름
        assertNull(PairRules.parse("kimbiseo://pair?v=1&h=192.168.1.23&p=8874&c=1234&f=$fp"))          // 짧은 코드
        assertNull(PairRules.parse("kimbiseo://pair?v=1&h=192.168.1.23&p=8874&c=12345678&f=3F2A91C0")) // 짧은 지문(QR 은 전체)
        assertNull(PairRules.parse("kimbiseo://pair?v=1&h=192.168.1.23&p=99999&c=12345678&f=$fp"))
    }

    @Test fun hostsAndFingerprint() {
        assertTrue(PairRules.lanHost("10.0.0.5")); assertTrue(PairRules.lanHost("172.20.1.1")); assertTrue(PairRules.lanHost("127.0.0.1"))
        assertFalse(PairRules.lanHost("172.32.0.1")); assertFalse(PairRules.lanHost("1.1.1.1")); assertFalse(PairRules.lanHost("192.168.1.300"))
        assertTrue(PairRules.lanHost("fd7a:115c:a1e0::1")); assertFalse(PairRules.lanHost("2001:db8::1"))
        assertEquals("3F2A91C000000000", PairRules.cleanFp("3f2a 91c0 0000 0000"))
        assertNull(PairRules.cleanFp("3F2A 91C0 ZZZZ 0000"))
        assertTrue(PairRules.fpMatches("3F2A91C000000000", fp)); assertTrue(PairRules.fpMatches(fp, fp))
        assertFalse(PairRules.fpMatches("3F2A91C000000001", fp)); assertFalse(PairRules.fpMatches("", fp))
        assertEquals("3F2A 91C0 0000 0000", PairRules.words(fp))
        assertEquals("12345678", PairRules.cleanCode("1234 5678")); assertNull(PairRules.cleanCode("1234abcd"))
        assertEquals("https://[fd7a::1]:8874", PairRules.baseUrl("fd7a::1", 8874))
        assertEquals("wss://192.168.1.23:8874", PairRules.baseUrl("192.168.1.23", 8874, ws = true))
    }

    @Test fun navPicksInstalledApp() {
        val none = NavRules.pick("강남역", "", { false }, "kr.kimbiseo.phone")
        assertEquals("https://map.kakao.com/?q=%EA%B0%95%EB%82%A8%EC%97%AD", none.uri)
        val naver = NavRules.pick("강남역 2번 출구", "naver", { it == NavRules.NAVER || it == NavRules.KAKAOMAP }, "kr.kimbiseo.phone")
        assertEquals(NavRules.NAVER, naver.pkg)
        assertTrue(naver.uri.startsWith("nmap://search?query=%EA%B0%95%EB%82%A8%EC%97%AD%202"))
        val first = NavRules.pick("부산역", "", { it == NavRules.TMAP || it == NavRules.GOOGLE }, "x")
        assertEquals(NavRules.TMAP, first.pkg)
        val g = NavRules.pick("부산역", "google", { true }, "x")
        assertEquals("google.navigation:q=%EB%B6%80%EC%82%B0%EC%97%AD", g.uri)
    }

    @Test fun contactNames() {
        val book = listOf("아랍공쥬님💕" to "010-1234-1111", "엄마" to "010 1234 2222", "엄마친구" to "010-1234-3333", "김철수 사장님" to "+82 10-1234-4444")
        val r = NameRules.rank(NameRules.cleanName("아랍공주한테"), book)
        assertEquals(1, r.list.size); assertEquals("01012341111", NameRules.digits(r.list[0].second))
        val m = NameRules.rank("엄마", book)
        assertEquals("엄마", m.list[0].first); assertEquals(1, m.list.size)
        assertEquals("01012344444", NameRules.digits(NameRules.rank("김철수", book).list[0].second))
        assertTrue(NameRules.rank("박영희", book).list.isEmpty())
    }

    @Test fun appNames() {
        val labels = listOf("YouTube", "YouTube Music", "카카오톡", "Chrome", "설정", "카카오맵")
        assertEquals(0, AppRules.best("유튜브", labels))
        assertEquals(1, AppRules.best("유튜브 뮤직", labels))
        assertEquals(2, AppRules.best("카톡", labels))
        assertEquals(3, AppRules.best("크롬 앱", labels))
        assertEquals(4, AppRules.best("설정", labels))
        assertEquals(-1, AppRules.best("넷플릭스", labels))
    }
}
