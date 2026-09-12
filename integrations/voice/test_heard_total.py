"""Hearing a quoted total in a transcript: boundaries and spoken-number forms."""
from decimal import Decimal

from integrations.voice.call import heard_total, words_to_number


def test_total_needs_word_boundaries():
    assert heard_total('the total is $1,535.00 delivered', Decimal('1535.00'))
    assert not heard_total('the total is $11,535.00 delivered', Decimal('1535.00'))
    assert not heard_total('11535 dollars 00', Decimal('1535.00'))
    assert not heard_total('quote 21535', Decimal('1535.00'))


def test_spoken_prices_are_heard():
    assert heard_total('total one thousand five hundred eighty five dollars', Decimal('1585.00'))
    assert heard_total('total fifteen thirty five dollars, still thursday', Decimal('1535.00'))
    assert heard_total('at 38 dollars 50 per sheet', Decimal('38.50'))
    assert heard_total('two thousand three hundred dollars delivered', Decimal('2300.00'))


def test_ambiguous_or_different_numbers_are_not_heard():
    assert not heard_total('total fifteen eighty five dollars', Decimal('1535.00'))
    assert not heard_total('fifteen thirty five', Decimal('1535.50'))
    assert not heard_total('', Decimal('1535.00'))
    assert not heard_total('no numbers here', None)


def test_words_to_number_forms():
    assert words_to_number('one thousand five hundred eighty five') == 1585
    assert words_to_number('fifteen hundred') == 1500
    assert words_to_number('fifteen thirty five') == 1535
    assert words_to_number('twenty five') == 25
    assert words_to_number('forty') == 40
    assert words_to_number('fifteen eighty five sixty') is None
