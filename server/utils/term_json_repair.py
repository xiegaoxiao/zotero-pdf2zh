"""Recover a missing final array delimiter without inventing term content."""
import json
import logging

logger = logging.getLogger(__name__)


def complete_term_json_array(output):
    text = output.strip()
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError as error:
        if error.pos != len(text) or not text.startswith('[') or not text.endswith('}'):
            return text
    try:
        terms = json.loads(text + ']')
    except json.JSONDecodeError:
        return text
    if not terms or not all(
        isinstance(term, dict)
        and all(isinstance(term.get(key), str) and term[key].strip() for key in ('src', 'tgt'))
        for term in terms
    ):
        return text
    logger.info('Recovered missing final term-array delimiter; retained %d complete entries', len(terms))
    return text + ']'
