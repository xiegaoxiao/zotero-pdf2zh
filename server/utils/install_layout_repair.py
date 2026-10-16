"""Install version-checked, idempotent hooks into a managed BabelDOC runtime."""
from pathlib import Path
import ast
import threading

_LOCK = threading.Lock()
MARKER = '# zotero-pdf2zh layout repair v2'
OLD_CONTINUATION_HINT = '''
- Read neighboring input items as context when a sentence continues across a page or column. Preserve the grammatical connection and do not turn an incomplete fragment into a standalone question or sentence. Keep each item's meaning in its own output item.
- Translate a multi-line title as one coherent academic title. Resolve the relationships between its subject, method and application before choosing the target-language word order.
'''
OLD_LINKED_HINT = '''
- Items explicitly linked by continues_to / continues_from form one continuous sentence across a page boundary. For these linked items ONLY, override the independent-unit rule: translate the connected sentence together and distribute its natural-language wording across the same two output slots so that reading them consecutively is fluent and grammatically correct. You MAY shift words across that boundary to satisfy target-language word order. Keep every placeholder and style tag in its original slot. Do not repeat or omit content; do not turn the first fragment into a standalone question. Later complete sentences remain in their original slot.
- Translate a multi-line title as one coherent academic title. Resolve the relationships between its subject, method and application before choosing the target-language word order. Infer technical terminology from the paper's research domain rather than using an unrelated everyday meaning.
'''
CONTINUATION_HINT = '''
- Translate a multi-line title as one coherent academic title. Resolve the relationships between its subject, method and application before choosing the target-language word order. Follow an input item's translation_hint when supplied; it is terminology guidance, not text to translate.
'''


def install_layout_repair(env_dir):
    root = Path(env_dir)
    sites = [root / 'Lib/site-packages', *root.glob('lib/python*/site-packages')]
    site = next((s for s in sites if (s / 'babeldoc/format/pdf/document_il/midend').is_dir()), None)
    if site is None:
        raise RuntimeError('BabelDOC site-packages not found in selected environment')
    folder = site / 'babeldoc/format/pdf/document_il/midend'
    hooks = {
        'paragraph_finder.py': ('    def process_page(self, page: Page):\n', 'deduplicate_text_layouts'),
        'styles_and_formulas.py': ('    def process_page(self, page: Page):\n', 'normalize_drop_cap_words'),
    }
    with _LOCK:
        changes = []
        for name, (anchor, func) in hooks.items():
            target = folder / name
            source = target.read_text(encoding='utf8')
            if MARKER not in source:
                old_hook = f'        # zotero-pdf2zh layout repair v1\n        from zotero_pdf_layout_repair import {func}\n        {func}(page)\n'
                source = source.replace(old_hook, '')
                if source.count(anchor) != 1:
                    raise RuntimeError(f'Unsupported BabelDOC hook: {name}; no files changed')
                args = 'page, self.translation_config' if func == 'normalize_drop_cap_words' else 'page'
                source = source.replace(anchor, anchor + f'        {MARKER}\n        from zotero_pdf_layout_repair import {func}\n        {func}({args})\n', 1)
                ast.parse(source)
                changes.append((target, source))
        render_file = folder / 'typesetting.py'
        render = render_file.read_text(encoding='utf8')
        render = render.replace('            from zotero_pdf_layout_repair import center_translated_title\n            center_translated_title(paragraph)  # zotero centered title repair\n', '')
        render_anchor = '            self.render_paragraph(paragraph, page, fonts)\n'
        render_hook = render_anchor + '            from zotero_pdf_layout_repair import center_translated_title\n            center_translated_title(paragraph, self.translation_config)  # zotero centered title repair\n'
        if render_hook not in render:
            if render.count(render_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC title renderer; no files changed')
            render = render.replace(render_anchor, render_hook, 1)
            ast.parse(render)
            changes.append((render_file, render))
        prompt_file = folder / 'il_translator_llm_only.py'
        prompt = prompt_file.read_text(encoding='utf8')
        original_prompt = prompt
        numeric_import = 'from babeldoc.format.pdf.document_il.utils.paragraph_helper import (\n    is_pure_numeric_paragraph,\n)\n'
        numeric_hook = 'from zotero_pdf_layout_repair import is_numeric_label as is_pure_numeric_paragraph  # zotero preserve numeric runs\n'
        if numeric_hook not in prompt:
            if prompt.count(numeric_import) != 1:
                raise RuntimeError('Unsupported BabelDOC numeric label filter; no files changed')
            prompt = prompt.replace(numeric_import, numeric_hook, 1)
        translator_file = folder / 'il_translator.py'
        translator = translator_file.read_text(encoding='utf8')
        original_translator = translator
        reference_anchor = '        if paragraph.vertical:\n'
        reference_guard = '        if id(paragraph) in getattr(self.translation_config, "_zotero_reference_paragraph_ids", ()):\n            return None, None  # zotero preserve bibliography\n'
        if reference_guard not in translator:
            if translator.count(reference_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC bibliography guard; no files changed')
            translator = translator.replace(reference_anchor, reference_guard + reference_anchor, 1)
        if numeric_hook not in translator:
            if translator.count(numeric_import) != 1:
                raise RuntimeError('Unsupported BabelDOC numeric input filter; no files changed')
            translator = translator.replace(numeric_import, numeric_hook, 1)
        weight_anchor = '        translate_input = self.get_translate_input(\n            paragraph, page_font_map, disable_rich_text_translate\n'
        weight_hook = '        if self.support_llm_translate:\n            from zotero_pdf_layout_repair import preserve_source_font_weight\n            disable_rich_text_translate = preserve_source_font_weight(paragraph, page_font_map, disable_rich_text_translate)  # zotero preserve source emphasis\n\n'
        if weight_hook not in translator:
            if translator.count(weight_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC font weight input; no files changed')
            translator = translator.replace(weight_anchor, weight_hook + weight_anchor, 1)
        weight_input_anchor = '        placeholder_id = 1\n'
        weight_input_hook = '        from zotero_pdf_layout_repair import preserve_source_font_weight  # zotero weight overflow guard\n\n'
        if weight_input_hook not in translator:
            if translator.count(weight_input_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC styled input; no files changed')
            translator = translator.replace(weight_input_anchor, weight_input_hook + weight_input_anchor, 1)
        overflow_anchor = '            if len(placeholders) > 40 and not disable_rich_text_translate:\n'
        overflow_hook = '            if len(placeholders) > 40 and not disable_rich_text_translate and preserve_source_font_weight(paragraph, page_font_map, True):  # zotero keep emphasis in long paragraphs\n'
        if overflow_hook not in translator:
            if translator.count(overflow_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC style overflow fallback; no files changed')
            translator = translator.replace(overflow_anchor, overflow_hook, 1)
        if translator != original_translator:
            ast.parse(translator)
            changes.append((translator_file, translator))
        prompt = prompt.replace(OLD_CONTINUATION_HINT, '')
        prompt = prompt.replace(OLD_LINKED_HINT, '')
        prompt_anchor = '- Produce fluent, professional $lang_out.\n'
        if CONTINUATION_HINT.strip() not in prompt:
            if prompt.count(prompt_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC prompt; no files changed')
            prompt = prompt.replace(prompt_anchor, prompt_anchor + CONTINUATION_HINT, 1)
            ast.parse(prompt)
        input_anchor = '            json_format_input_str = json.dumps(\n'
        prompt = prompt.replace('            from zotero_pdf_layout_repair import mark_continued_inputs\n            mark_continued_inputs(json_format_input, batch_paragraph, should_translate_paragraph)\n', '')
        old_input_hook = '            from zotero_pdf_layout_repair import prepare_continued_inputs, redistribute_continued_outputs\n            continuation_plans = prepare_continued_inputs(json_format_input, batch_paragraph, should_translate_paragraph)\n'
        prompt = prompt.replace(old_input_hook, '')
        input_hook = '            from zotero_pdf_layout_repair import prepare_continued_inputs, redistribute_continued_outputs, annotate_title_terms\n            annotate_title_terms(json_format_input)\n            continuation_plans = prepare_continued_inputs(json_format_input, batch_paragraph, should_translate_paragraph)\n'
        if input_hook not in prompt:
            if prompt.count(input_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC batch input; no files changed')
            prompt = prompt.replace(input_anchor, input_hook + input_anchor, 1)
        result_anchor = '            if len(translation_results) != len(inputs):\n'
        result_hook = '            redistribute_continued_outputs(translation_results, continuation_plans)\n\n'
        if result_hook not in prompt:
            if prompt.count(result_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC batch output; no files changed')
            prompt = prompt.replace(result_anchor, result_hook + result_anchor, 1)
        if prompt != original_prompt:
            ast.parse(prompt)
            changes.append((prompt_file, prompt))
        backend_file = folder.parent / 'backend/pdf_creater.py'
        backend = backend_file.read_text(encoding='utf8')
        original_backend = backend
        backend_anchor = '            gc_level = 1\n'
        backend_hook = '            from zotero_pdf_rotated_labels import repair_rotated_labels\n            repair_rotated_labels(pdf, translation_config, self.docs)\n'
        if backend_hook not in backend:
            if backend.count(backend_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC PDF writer; no files changed')
            backend = backend.replace(backend_anchor, backend_hook + backend_anchor, 1)
        subset_anchor = '        pdf.subset_fonts(fallback=False)\n'
        subset_hook = '        from zotero_pdf_safe_font_subset import subset_fonts_preserving_source\n        subset_fonts_preserving_source(pdf)  # zotero preserve source font encoding\n'
        if subset_hook not in backend:
            if backend.count(subset_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC font subsetter; no files changed')
            backend = backend.replace(subset_anchor, subset_hook, 1)
        if backend != original_backend:
            ast.parse(backend)
            changes.append((backend_file, backend))
        term_file = folder / 'automatic_term_extractor.py'
        term_source = term_file.read_text(encoding='utf8')
        term_anchor = '        return llm_output.strip()\n'
        term_hook = '        from zotero_pdf_term_json_repair import complete_term_json_array\n        return complete_term_json_array(llm_output)  # zotero preserve complete term entries\n'
        if term_hook not in term_source:
            if term_source.count(term_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC term JSON cleaner; no files changed')
            term_source = term_source.replace(term_anchor, term_hook, 1)
            ast.parse(term_source)
            changes.append((term_file, term_source))
        high_level_file = folder.parent.parent / 'high_level.py'
        high_level = high_level_file.read_text(encoding='utf8')
        reference_anchor = '    support_llm_term_extraction = translator_supports_llm(term_extraction_engine)\n'
        reference_hook = '    from zotero_pdf_reference_filter import preserve_reference_paragraphs\n    preserve_reference_paragraphs(docs, translation_config)  # zotero preserve bibliography\n\n'
        if reference_hook not in high_level:
            if high_level.count(reference_anchor) != 1:
                raise RuntimeError('Unsupported BabelDOC bibliography stage; no files changed')
            high_level = high_level.replace(reference_anchor, reference_hook + reference_anchor, 1)
            ast.parse(high_level)
            changes.append((high_level_file, high_level))
        reference_module = Path(__file__).with_name('reference_filter.py').read_text(encoding='utf8')
        reference_helper = site / 'zotero_pdf_reference_filter.py'
        reference_changed = not reference_helper.exists() or reference_helper.read_text(encoding='utf8') != reference_module
        if reference_changed:
            reference_helper.write_text(reference_module, encoding='utf8')
        module = Path(__file__).with_name('pdf_layout_repair.py').read_text(encoding='utf8')
        helper = site / 'zotero_pdf_layout_repair.py'
        helper_changed = not helper.exists() or helper.read_text(encoding='utf8') != module
        if helper_changed:
            helper.write_text(module, encoding='utf8')
        rotated_module = Path(__file__).with_name('rotated_labels.py').read_text(encoding='utf8')
        rotated_helper = site / 'zotero_pdf_rotated_labels.py'
        rotated_changed = not rotated_helper.exists() or rotated_helper.read_text(encoding='utf8') != rotated_module
        if rotated_changed:
            rotated_helper.write_text(rotated_module, encoding='utf8')
        subset_module = Path(__file__).with_name('safe_font_subset.py').read_text(encoding='utf8')
        subset_helper = site / 'zotero_pdf_safe_font_subset.py'
        subset_changed = not subset_helper.exists() or subset_helper.read_text(encoding='utf8') != subset_module
        if subset_changed:
            subset_helper.write_text(subset_module, encoding='utf8')
        term_module = Path(__file__).with_name('term_json_repair.py').read_text(encoding='utf8')
        term_helper = site / 'zotero_pdf_term_json_repair.py'
        term_changed = not term_helper.exists() or term_helper.read_text(encoding='utf8') != term_module
        if term_changed:
            term_helper.write_text(term_module, encoding='utf8')
        for target, source in changes:
            backup = target.with_suffix(target.suffix + '.before_zotero_layout_repair')
            if not backup.exists():
                backup.write_bytes(target.read_bytes())
            target.write_text(source, encoding='utf8')
    return bool(changes) or helper_changed or rotated_changed or subset_changed or term_changed or reference_changed


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', nargs='?', default=str(Path(__file__).resolve().parent.parent / 'zotero-pdf2zh-next-venv'))
    options = parser.parse_args()
    print('Layout repair installed.' if install_layout_repair(options.environment) else 'Layout repair already installed.')
