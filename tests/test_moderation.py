"""
Tests for app/moderation.py.
Covers validation rules, offensive word detection, leetspeak, zero-width chars,
reserved handles, and leaderboard fallback sanitization.
"""

import unittest
from app.moderation import (
    validate_display_name,
    validate_username,
    sanitize_leaderboard_name,
    is_inappropriate_text,
    is_reserved_name,
    strip_invisible_characters,
)


class ModerationTests(unittest.TestCase):
    def test_valid_display_names(self):
        valid_names = [
            "John Doe",
            "Maria Müller",
            "SpeedyLearner",
            "Alex-99",
            "Dr. Smith",
            "Anna_K",
            "User 123",
            "Cassandra",
            "Classic Learner",
            "Pascal",
            "Siddharth",
            "Titus",
            "Kasper",
            "Butter",
            "Glass House",
        ]
        for name in valid_names:
            is_valid, err = validate_display_name(name)
            self.assertTrue(is_valid, f"Expected '{name}' to be valid, got error: {err}")
            self.assertIsNone(err)

    def test_valid_usernames(self):
        valid_usernames = [
            "johndoe",
            "maria_m",
            "alex-99",
            "user123",
            "studying_hard",
        ]
        for u in valid_usernames:
            is_valid, err = validate_username(u)
            self.assertTrue(is_valid, f"Expected '{u}' to be valid, got error: {err}")
            self.assertIsNone(err)

    def test_length_constraints(self):
        # Too short
        self.assertFalse(validate_display_name("a")[0])
        self.assertFalse(validate_username("ab")[0])

        # Too long (>30)
        self.assertFalse(validate_display_name("a" * 31)[0])
        self.assertFalse(validate_username("a" * 31)[0])

        # Empty / whitespace
        self.assertFalse(validate_display_name("   ")[0])
        self.assertFalse(validate_username("   ")[0])

    def test_username_character_set(self):
        # Spaces or special characters not allowed in username
        self.assertFalse(validate_username("john doe")[0])
        self.assertFalse(validate_username("john.doe")[0])
        self.assertFalse(validate_username("john@doe")[0])

    def test_reserved_names(self):
        reserved_list = [
            "admin",
            "Admin",
            "ADMINISTRATOR",
            "studiamo",
            "studiamo_official",
            "moderator",
            "system",
            "official_support",
            "null",
            "undefined",
            "anonymous",
        ]
        for name in reserved_list:
            self.assertTrue(is_reserved_name(name), f"Expected '{name}' to be reserved")
            is_valid_dn, _ = validate_display_name(name)
            self.assertFalse(is_valid_dn, f"Expected display name '{name}' to be blocked")
            is_valid_un, _ = validate_username(name)
            self.assertFalse(is_valid_un, f"Expected username '{name}' to be blocked")

    def test_profanity_and_slurs(self):
        bad_words = [
            "fuck",
            "fucking_legend",
            "bitch",
            "asshole",
            "nigger",
            "faggot",
            "hitler",
            "arschloch",
            "hurensohn",
            "fotze",
            "schlampe",
        ]
        for word in bad_words:
            self.assertTrue(is_inappropriate_text(word), f"Expected '{word}' to be inappropriate")
            is_valid, _ = validate_display_name(word)
            self.assertFalse(is_valid, f"Expected display name '{word}' to be rejected")
            is_valid_u, _ = validate_username(word)
            self.assertFalse(is_valid_u, f"Expected username '{word}' to be rejected")

    def test_leetspeak_and_evasions(self):
        evasion_words = [
            "f*ck",
            "f.u.c.k",
            "f u c k",
            "fuuuuuck",
            "b!tch",
            "@sshole",
            "sh1t",
            "n1gg4",
            "h1tl3r",
            "f@ggot",
            "huren_sohn",
        ]
        for word in evasion_words:
            self.assertTrue(is_inappropriate_text(word), f"Expected evasion '{word}' to be caught")
            is_valid, _ = validate_display_name(word)
            self.assertFalse(is_valid, f"Expected display name '{word}' to be rejected")

    def test_invisible_zero_width_characters(self):
        zero_width_name = "f\u200bu\u200cc\u200dk"
        self.assertEqual(strip_invisible_characters(zero_width_name), "fuck")
        self.assertTrue(is_inappropriate_text(zero_width_name))

    def test_sanitize_leaderboard_name(self):
        self.assertEqual(sanitize_leaderboard_name("ValidUser", 1), "ValidUser")
        self.assertEqual(sanitize_leaderboard_name("", 5), "Learner 5")
        self.assertEqual(sanitize_leaderboard_name(None, 3), "Learner 3")
        self.assertEqual(sanitize_leaderboard_name("fuck_this", 4), "Learner 4")
        self.assertEqual(sanitize_leaderboard_name("Admin", 2), "Learner 2")


if __name__ == "__main__":
    unittest.main()
