import unittest,copy,re
from pathlib import Path
from operation1million import employers as e,export

class AllCompanyTests(unittest.TestCase):
 def test_every_catalog_employer_has_a_registered_display(self):
  sql=(Path(__file__).parents[1]/'data/config/schema.sql').read_text(encoding='utf-8')
  block=sql.split('INSERT INTO companies',1)[1].split('ON CONFLICT',1)[0]
  names=re.findall(r"\('[^']+', '([^']+)'\)",block)
  self.assertGreater(len(names),40)
  self.assertEqual([n for n in names if e._plain(n) not in e.ALIASES],[])

 def test_common_non_marvell_aliases_use_same_identity(self):
  for names in [('Renesas','Renesas Electronics Corporation','Renesas Electronics America, Inc.'),
    ('NXP','NXP USA, Inc.','NXP Semiconductors'),('Quadric','quadric','quadric.io'),
    ('Astera Labs','Asteralabs'),('onsemi','ON Semiconductor Corporation'),
    ('Intel','100 Intel Corporation','500 Intel Ireland Ltd.'),('HPE','Hewlett Packard Enterprise')]:
   with self.subTest(names=names):
    self.assertEqual(len({e.identity(n) for n in names}),1)
    self.assertEqual(len({e.display(n) for n in names}),1)

 def test_unregistered_employers_have_one_label_across_all_tabs_and_exports(self):
  names=['Example Instruments, Inc.','EXAMPLE INSTRUMENTS','example instruments','Example Instruments LLC']
  state={k:[{'id':k,'company':n,'title':'RTL Engineer','jobs':[{'url':'https://example.test/'+k,'company':n}]}]
         for k,n in zip(('pending','backlog','applied','skipped'),names)}
  original=copy.deepcopy(state)
  e.label_queue(state)
  self.assertEqual({g['company'] for gs in state.values() for g in gs},{'Example Instruments'})
  self.assertEqual({j['company'] for gs in state.values() for g in gs for j in g['jobs']},{'Example Instruments'})
  rows=export.rows((k,g) for k,gs in original.items() for g in gs)
  self.assertEqual({r[1] for r in rows},{'Example Instruments'})
  reversed_state={k:list(reversed(v)) for k,v in reversed(list(original.items()))}
  self.assertEqual(e.label_queue(reversed_state),state)

 def test_unconfirmed_names_and_distinct_businesses_stay_separate(self):
  self.assertNotEqual(e.identity('Intel Staffing Services'),e.identity('Intel'))
  self.assertNotEqual(e.identity('Instagram'),e.identity('Meta'))
  self.assertNotEqual(e.identity('Analogic'),e.identity('Analog Devices'))
  self.assertEqual(e.display('A & B Instruments'),'A & B Instruments')

 def test_alias_collisions_fail_instead_of_silently_merging(self):
  with self.assertRaises(ValueError):e.build_aliases([('One',('Acme',)),('Two',('Acme, Inc.',))])
