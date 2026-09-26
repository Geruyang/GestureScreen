"""Predeclared validation-only accuracy ranking and regression guards."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from optimization_campaign import select_rounds


def row(name='base', accuracy=.75, loss=.7, f1=.78, fist=.5, palm=.5):
    return dict(name=name, mean_val_accuracy=accuracy, mean_val_loss=loss,
                mean_val_macro_f1=f1, mean_personal_recall=dict(FIST=fist, PALM=palm),
                val_correct_total=round(600*accuracy),
                personal_correct_total=dict(FIST=round(24*fist), PALM=round(6*palm)))


class AccuracyCampaignTests(unittest.TestCase):
    def state(self, *rows):
        return dict(selection_metric='val_accuracy',
                    selection_guards=dict(macro_f1_max_drop=.01), rounds=list(rows))

    def test_accuracy_not_loss_ranks_new_campaign(self):
        state = self.state(row(), row('new', accuracy=.8, loss=.9))
        self.assertEqual(select_rounds(state)['name'], 'new')

    def test_macro_f1_guard(self):
        state = self.state(row(), row('new', accuracy=.9, f1=.76))
        self.assertEqual(select_rounds(state)['name'], 'base')
        self.assertFalse(state['rounds'][1]['eligible'])

    def test_each_personal_class_guard(self):
        for label in ('fist', 'palm'):
            state = self.state(row(), row('new', accuracy=.9, **{label: .4}))
            self.assertEqual(select_rounds(state)['name'], 'base')

    def test_f1_then_loss_then_earlier_ties(self):
        first = row()
        self.assertIs(select_rounds(self.state(first, copy.deepcopy(first))), first)
        self.assertEqual(select_rounds(self.state(row(), row('f1', f1=.79)))['name'], 'f1')
        self.assertEqual(select_rounds(self.state(row(), row('loss', loss=.6)))['name'], 'loss')

    def test_legacy_loss_selection_preserved(self):
        self.assertEqual(select_rounds(dict(rounds=[row(), row('low', accuracy=.6, loss=.5)]))['name'], 'low')


if __name__ == '__main__':
    unittest.main()
