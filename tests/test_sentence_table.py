from copy import deepcopy

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QAbstractItemView, QStyle, QStyleOptionViewItem

from src.models.sentence import Sentence, Word
from src.ui.sentence_table import SentenceTable


@pytest.fixture
def sentence_table(qtbot):
    table = SentenceTable()
    qtbot.addWidget(table)
    table.resize(1100, 400)
    table.set_sentences([
        Sentence(f"Sentence {row + 1}.", row * 2 + 0.1, row * 2 + 0.9,
                 [Word("Sentence", row * 2 + 0.1, row * 2 + 0.4),
                  Word(f"{row + 1}.", row * 2 + 0.5, row * 2 + 0.9)],
                 review_reasons=["Confirm this boundary."])
        for row in range(4)
    ], 8)
    table.show()
    qtbot.waitExposed(table)
    return table


def select_rows(table, rows):
    table.clearSelection()
    for row in rows:
        table.selectionModel().select(
            table.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)


def click_checkbox(qtbot, table, row, column, modifiers=Qt.NoModifier):
    index = table.model().index(row, column)
    table.scrollTo(index)
    option = QStyleOptionViewItem()
    option.rect = table.visualRect(index)
    table.itemDelegateForColumn(column).initStyleOption(option, index)
    indicator = table.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, option, table)
    qtbot.mouseClick(table.viewport(), Qt.LeftButton, modifiers, indicator.center())
    if modifiers & Qt.ShiftModifier:
        qtbot.keyRelease(table.viewport(), Qt.Key_Shift)


def test_ctrl_and_shift_select_multiple_rows(sentence_table, qtbot):
    table = sentence_table
    assert table.selectionMode() == QAbstractItemView.ExtendedSelection
    for row, modifiers in ((0, Qt.NoModifier), (2, Qt.ControlModifier)):
        qtbot.mouseClick(table.viewport(), Qt.LeftButton, modifiers,
                         table.visualItemRect(table.item(row, 1)).center())
    assert table.selected_rows() == [0, 2]
    qtbot.mouseClick(table.viewport(), Qt.LeftButton, Qt.ControlModifier,
                     table.visualItemRect(table.item(0, 1)).center())
    assert table.selected_rows() == [2]
    qtbot.mouseClick(table.viewport(), Qt.LeftButton, Qt.NoModifier,
                     table.visualItemRect(table.item(0, 1)).center())
    qtbot.mouseClick(table.viewport(), Qt.LeftButton, Qt.ShiftModifier,
                     table.visualItemRect(table.item(3, 1)).center())
    assert table.selected_rows() == [0, 1, 2, 3]
    qtbot.keyRelease(table.viewport(), Qt.Key_Shift)


@pytest.mark.parametrize("field,column", [("include", 6), ("reviewed", 7)])
@pytest.mark.parametrize("checked", [False, True])
def test_bulk_changes_only_selected_rows(sentence_table, field, column, checked):
    table = sentence_table
    for sentence in table.sentences:
        setattr(sentence, field, not checked)
    table.refresh()
    before = deepcopy(table.sentences)
    select_rows(table, [0, 2])
    updates = []
    table.updated.connect(lambda: updates.append(True))
    table.set_checked(field, checked, table.selected_rows())
    assert table.selected_rows() == [0, 2]
    assert len(updates) == 1
    for row, sentence in enumerate(table.sentences):
        expected = checked if row in (0, 2) else not checked
        assert getattr(sentence, field) is expected
        assert table.item(row, column).checkState() == (Qt.Checked if expected else Qt.Unchecked)
        original = deepcopy(before[row])
        setattr(original, field, expected)
        assert sentence == original
        if field == "reviewed":
            assert sentence.needs_review is (not expected)
            assert table.item(row, 8).text() == ("Reviewed" if expected else "Needs review")


@pytest.mark.parametrize("field", ["include", "reviewed"])
def test_select_all_and_clear_all_preserve_empty_selection(sentence_table, field):
    table = sentence_table
    table.clearSelection()
    table.set_checked(field, True)
    assert all(getattr(sentence, field) for sentence in table.sentences)
    assert table.checkbox_state(field) == Qt.Checked
    table.set_checked(field, False)
    assert not any(getattr(sentence, field) for sentence in table.sentences)
    assert table.checkbox_state(field) == Qt.Unchecked
    assert table.selected_rows() == []


@pytest.mark.parametrize("field", ["include", "reviewed"])
def test_mixed_checkbox_state_and_empty_bulk_action(sentence_table, field):
    table = sentence_table
    table.set_checked(field, False)
    table.set_checked(field, True, [0])
    assert table.checkbox_state(field) == Qt.PartiallyChecked
    assert table.checkbox_state(field, [0]) == Qt.Checked
    assert table.checkbox_state(field, [1, 2]) == Qt.Unchecked
    assert table.checkbox_state(field, []) == Qt.Unchecked
    before = deepcopy(table.sentences)
    table.set_checked(field, False, [])
    assert table.sentences == before


def test_invalid_bulk_input_is_atomic(sentence_table):
    table = sentence_table
    before = deepcopy(table.sentences)
    with pytest.raises(ValueError, match="existing"):
        table.set_checked("include", False, [0, 10])
    with pytest.raises(ValueError, match="Include or Reviewed"):
        table.set_checked("text", False)
    assert table.sentences == before


def test_edit_and_single_checkbox_preserve_multi_selection(sentence_table):
    table = sentence_table
    select_rows(table, [0, 2])
    table.set_checked("reviewed", True)
    table.item(0, 1).setText("Edited sentence.")
    assert table.selected_rows() == [0, 2]
    assert not table.sentences[0].reviewed and table.sentences[2].reviewed
    table.item(2, 6).setCheckState(Qt.Unchecked)
    assert table.selected_rows() == [0, 2]
    assert table.sentences[0].include and not table.sentences[2].include


@pytest.mark.parametrize("rows", [[], [0, 2]])
def test_merge_and_split_require_one_selected_row(sentence_table, rows):
    table = sentence_table
    select_rows(table, rows)
    before = deepcopy(table.sentences)
    with pytest.raises(ValueError, match="exactly one"):
        table.merge_selected()
    with pytest.raises(ValueError, match="exactly one"):
        table.split_selected(1)
    assert table.sentences == before


def test_selection_remains_valid_after_merge_split_and_new_recording(sentence_table):
    table = sentence_table
    table.selectRow(2)
    table.merge_selected()
    assert table.selected_rows() == [2] and len(table.sentences) == 3
    table.split_selected(2)
    assert table.selected_rows() == [2] and len(table.sentences) == 4
    table.selectAll()
    table.set_sentences([Sentence("New recording.", 0, 1)], 1)
    assert table.selected_rows() == [0]
    table.set_sentences([], 0)
    assert table.selected_rows() == []


@pytest.mark.parametrize("field,column", [("include", 6), ("reviewed", 7)])
@pytest.mark.parametrize("checked", [False, True])
@pytest.mark.parametrize("anchor,target", [(1, 3), (3, 1)])
def test_shift_checkbox_sets_inclusive_range(sentence_table, qtbot, field, column, checked,
                                           anchor, target):
    table = sentence_table
    table.set_checked(field, not checked)
    before = deepcopy(table.sentences)
    click_checkbox(qtbot, table, anchor, column)
    assert getattr(table.sentences[anchor], field) is checked
    updates = []
    table.updated.connect(lambda: updates.append(True))
    click_checkbox(qtbot, table, target, column, Qt.ShiftModifier)
    assert len(updates) == 1
    for row, sentence in enumerate(table.sentences):
        expected = checked if 1 <= row <= 3 else not checked
        original = deepcopy(before[row])
        setattr(original, field, expected)
        assert sentence == original
        assert table.item(row, column).checkState() == (Qt.Checked if expected else Qt.Unchecked)
        if field == "reviewed":
            assert sentence.needs_review is (not expected)


@pytest.mark.parametrize("field,column", [("include", 6), ("reviewed", 7)])
def test_repeated_shift_checkbox_clicks_keep_anchor_until_normal_click(sentence_table, qtbot,
                                                                     field, column):
    table = sentence_table
    table.set_checked(field, False)
    click_checkbox(qtbot, table, 0, column)
    click_checkbox(qtbot, table, 2, column, Qt.ShiftModifier)
    click_checkbox(qtbot, table, 3, column, Qt.ShiftModifier)
    assert all(getattr(sentence, field) for sentence in table.sentences)
    click_checkbox(qtbot, table, 1, column, Qt.ShiftModifier)
    assert [getattr(sentence, field) for sentence in table.sentences] == [False, False, True, True]
    click_checkbox(qtbot, table, 3, column)
    click_checkbox(qtbot, table, 2, column, Qt.ShiftModifier)
    assert not any(getattr(sentence, field) for sentence in table.sentences)


def test_checkbox_range_anchors_are_independent_and_no_anchor_changes_only_one(sentence_table, qtbot):
    table = sentence_table
    table.set_checked("include", False)
    click_checkbox(qtbot, table, 0, 6)
    click_checkbox(qtbot, table, 3, 7, Qt.ShiftModifier)
    assert [sentence.reviewed for sentence in table.sentences] == [False, False, False, True]
    click_checkbox(qtbot, table, 2, 6, Qt.ShiftModifier)
    assert [sentence.include for sentence in table.sentences] == [True, True, True, False]
    click_checkbox(qtbot, table, 1, 7, Qt.ShiftModifier)
    assert [sentence.reviewed for sentence in table.sentences] == [False, True, True, True]


def test_checkbox_anchor_survives_text_edits_but_resets_for_new_sentences(sentence_table, qtbot):
    table = sentence_table
    table.set_checked("include", False)
    click_checkbox(qtbot, table, 0, 6)
    table.item(1, 1).setText("Edited sentence.")
    click_checkbox(qtbot, table, 2, 6, Qt.ShiftModifier)
    assert [sentence.include for sentence in table.sentences] == [True, True, True, False]
    table.set_sentences([Sentence(str(row), row * 2, row * 2 + 1) for row in range(4)], 8)
    click_checkbox(qtbot, table, 2, 6, Qt.ShiftModifier)
    assert [sentence.include for sentence in table.sentences] == [True, True, False, True]


@pytest.mark.parametrize("operation", ["merge", "split"])
def test_checkbox_anchor_resets_after_merge_or_split(sentence_table, qtbot, operation):
    table = sentence_table
    click_checkbox(qtbot, table, 0, 7)
    table.clearSelection()
    table.selectRow(2)
    if operation == "merge":
        table.merge_selected()
    else:
        table.split_selected(1)
    click_checkbox(qtbot, table, 2, 7, Qt.ShiftModifier)
    assert [row for row, sentence in enumerate(table.sentences) if sentence.reviewed] == [0, 2]


def test_shift_click_outside_checkbox_or_on_disabled_table_does_not_change_values(sentence_table,
                                                                                qtbot):
    table = sentence_table
    click_checkbox(qtbot, table, 0, 7)
    before = deepcopy(table.sentences)
    cell = table.visualItemRect(table.item(3, 7))
    qtbot.mouseClick(table.viewport(), Qt.LeftButton, Qt.ShiftModifier, cell.topRight())
    qtbot.keyRelease(table.viewport(), Qt.Key_Shift)
    assert table.sentences == before
    table.setEnabled(False)
    click_checkbox(qtbot, table, 3, 7, Qt.ShiftModifier)
    assert table.sentences == before
