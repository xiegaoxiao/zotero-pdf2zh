import json
import unittest
from utils.term_json_repair import complete_term_json_array


class TermJsonRepairTests(unittest.TestCase):
    def test_valid_json_is_unchanged(self):
        for text in ['[]','[{"src":"FER","tgt":"表情识别"}]','{"src":"ViT","tgt":"ViT"}']:
            self.assertEqual(complete_term_json_array(text),text)

    def test_only_missing_array_closer_preserves_all_complete_pairs(self):
        terms=[{'src':'static facial expression','tgt':'静态面部表情'}, {'src':'video','tgt':'视频'}]
        text=json.dumps(terms,ensure_ascii=False,indent=2)
        with self.assertLogs('utils.term_json_repair',level='INFO') as logs:
            repaired=complete_term_json_array(text[:-1])
        self.assertEqual(json.loads(repaired),terms)
        self.assertNotIn('静态面部表情',' '.join(logs.output))

    def test_incomplete_term_value_is_not_fabricated(self):
        text='[{"src":"FER","tgt":"面部表'
        self.assertEqual(complete_term_json_array(text),text)

    def test_missing_object_closer_is_not_repaired(self):
        text='[{"src":"FER","tgt":"面部表情识别"'
        self.assertEqual(complete_term_json_array(text),text)

    def test_internal_bad_quotes_are_not_repaired(self):
        text='[{"src":"FER","tgt":"面部"表情识别"}'
        self.assertEqual(complete_term_json_array(text),text)

    def test_non_term_objects_and_empty_values_are_not_repaired(self):
        for text in ['[{"message":"not terms"}', '[{"src":"FER","tgt":""}', '[{"src":"FER","tgt":42}', '[42,{"src":"FER","tgt":"表情识别"}']:
            self.assertEqual(complete_term_json_array(text),text)

    def test_brackets_inside_escaped_strings_do_not_confuse_recovery(self):
        terms=[{'src':'a "quoted" [term]','tgt':'带有方括号[]的术语'}]
        text=json.dumps(terms,ensure_ascii=False)
        self.assertEqual(json.loads(complete_term_json_array(text[:-1])),terms)

    def test_surrounding_explanations_remain_invalid(self):
        text='Here are terms: [{"src":"FER","tgt":"表情识别"}'
        self.assertEqual(complete_term_json_array(text),text)


if __name__=='__main__':
    unittest.main()
