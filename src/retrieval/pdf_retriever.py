# pdf_retriever.py
# Required when executed as the main program.
import os, sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app_helper
app_helper.initialize(os.path.splitext(os.path.basename(__file__))[0])
###

import logging
import textwrap
logger:logging.Logger = logging.getLogger(os.getenv('LOGGER_NAME'))

from agentflow.core.agent import Agent
from agentflow.core.parcel import BinaryParcel, Parcel, TextParcel
from services.file_service import FileService
from services.kg_service import Topic
from services.llm_service import LlmService
from retrieval import part_str
# import retrieval.extract_tool as et
from retrieval.extract_tool import FactConceptExtractor, SectionPairer
from retrieval.pdf_tool import PdfImport



class PdfRetriever(Agent):
    TOPIC_FILE_UPLOAD = "FileUpload/Pdf/Retrieval"
    TOPIC_RETRIEVED = "Retrieved/Pdf/Retrieval"


    def __init__(self, config:dict):
        logger.debug(f"config: {config}")
        super().__init__(name='pdf.retrieval.wp', agent_config=config)


    def on_connected(self):
        logger.debug(f"on_connected")
        self.subscribe(PdfRetriever.TOPIC_FILE_UPLOAD, topic_handler=self._handle_retrieval)


    def _handle_retrieval(self, topic, pcl:BinaryParcel):
        # Upload the file
        kg_name = pcl.content.get('kg_name', 0)
        # logger.info(f"topic: {topic}, pcl: {pcl}")
        
        pcl_file:Parcel = self.publish_sync(FileService.TOPIC_FILE_UPLOAD, BinaryParcel(pcl.content), timeout=40)
        if pcl_file.error:
            raise RuntimeError(f"File upload failed: {pcl_file.error}")
        file_info = pcl_file.content
        logger.info(f"file_info: {file_info}")
        # file_info: {
            # 'file_id': file_id,
            # 'filename': filename,
            # 'mime_type': mime_type,
            # 'encoding': encoding,
            # 'file_path': file_path,
            # 'toc': {..},  # json
            # 'meta': {..}, # dict
        # }
        
        topic_triplets_add = f'{kg_name}/{Topic.TRIPLETS_ADD.value}'
        logger.verbose(f"topic_triplets_add: {topic_triplets_add}")

        app_helper.report_progress("PDF uploaded. Reading page text and checking for tables and images.")
        pages = self.read_pages(file_info['file_path'])
        app_helper.report_progress(f"Read {len(pages)} PDF pages.")

        meta = file_info.get('meta', {})
        meta['filename'] = file_info['filename']
        meta['mime_type'] = file_info['mime_type']
        meta['encoding'] = file_info['encoding']
        meta['file_path'] = file_info['file_path']
        meta['title'] = meta['title'] if 'title' in meta else file_info['filename']
            
        toc = [(meta['title'], 
                0, 
                len(pages), 
                file_info['toc'] if 'toc' in file_info else [])]
        logger.debug(f"toc: {toc}")

        def process_page(page_number, page_content, attempt):
            """Process a single page, extracting and publishing triplets."""
            label = f"Page {page_number + 1}/{len(pages)}"
            logger.info(f"Page {page_number}: {part_str(page_content, 150)}")
            sections = self.locate_sections(page_number, toc)
            logger.debug(f"sections: {sections}")
            retry_width = 1400 if attempt == 1 else 950
            passages = textwrap.wrap(page_content, width=retry_width, break_long_words=False) if attempt else [page_content]
            triplets = []
            for index, passage in enumerate(passages, 1):
                passage_label = f"{label}, passage {index}/{len(passages)}" if len(passages) > 1 else label
                triplets.extend(self.extract_triplets(passage, sections, meta, passage_label))
            logger.verbose(f"triplets: {triplets[:5]}..")
            app_helper.report_progress(f"{label} · writing {len(triplets)} triplets to Neo4j.")
            written = self.publish_sync(topic_triplets_add, {
                'file_id': file_info['file_id'],
                'page_number': page_number,
                'kg_name': kg_name,
                'triplets': triplets,
            }, timeout=120)
            if written.error:
                raise RuntimeError(f"Graph write failed: {written.error}")
            app_helper.report_progress(f"{label} · graph write complete.")

        failed_pages = []
        processed_pages = 0
        for page_number, page_content in enumerate(pages):
            if not page_content.strip():
                app_helper.report_progress(f"Page {page_number + 1}/{len(pages)} · no readable content.")
                continue
            max_attempts = 3
            attempt = 0
            # Retry processing the page if an error occurs in max_attempts times.
            while attempt < max_attempts:
                try:
                    process_page(page_number, page_content, attempt)
                    processed_pages += 1
                    break  # Exit loop if successful
                except Exception as e:
                    attempt += 1
                    logger.warning(f"Error processing page {page_number} (Attempt {attempt}/{max_attempts})")
                    logger.exception(e)
                    if attempt == max_attempts:
                        logger.error(f"Skipping page {page_number} after {max_attempts} failed attempts.")
                        failed_pages.append(page_number + 1)
                    else:
                        app_helper.report_progress(f"Page {page_number + 1}/{len(pages)} · retrying extraction.")
                        
        result = {
            'file_id': file_info['file_id'],
            'filename': file_info['filename'],
            'kg_name': kg_name,
            'processed_pages': processed_pages,
            'failed_pages': failed_pages,
        }
        self.publish(PdfRetriever.TOPIC_RETRIEVED, result)
        return result


    def _ask_llm(self, params):
        reply = self.publish_sync(LlmService.TOPIC_LLM_PROMPT, TextParcel(params), timeout=180)
        if reply.error:
            raise RuntimeError(f"LLM request failed: {reply.error}")
        return reply.content['response'].strip()
        

    chapter = tuple[str, int, int, list['chapter']]
    def locate_sections(self, page_number: int, toc: list[chapter], parent_hierarchy: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
        """
        遞迴查找多層章節結構，根據頁碼返回所有匹配的層級，並以 list of tuples 格式返回。
        
        :param page_number: 查詢的頁碼
        :param toc: 目錄結構 (遞迴形式)
        :param parent_hierarchy: 當前章節的父層級，用於組合完整層次
        :return: 包含所有匹配層級的 list of tuples

        Example:
        toc = [
            ('chapter1', 1, 9, [
                ('ch1-1', 1, 4, [
                    ('ch1-1-1', 1, 2, []),
                    ('ch1-1-2', 2, 4, [])
                ]),
                ('ch1-2', 4, 9, [])
            ]),
            ('chapter2', 10, 15, [
                ('ch2-1', 10, 12, []),
                ('ch2-2', 13, 15, [])
            ])
        ]
        
        Result of toc:
        Page 2 belongs to: [('chapter1',), ('chapter1', 'ch1-1'), ('chapter1', 'ch1-1', 'ch1-1-1'), ('chapter1', 'ch1-1', 'ch1-1-2')]
        Page 5 belongs to: [('chapter1',), ('chapter1', 'ch1-2')]
        Page 12 belongs to: [('chapter2',), ('chapter2', 'ch2-1')]
        Page 20 belongs to: []
        """
        def find_sections(page_number: int, toc: list[PdfRetriever.chapter], parent_hierarchy: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
            matches = []
            for ch in toc:
                name, start_page, end_page, subchapters = ch
                current_hierarchy = parent_hierarchy + (name,)
                
                if start_page <= page_number <= end_page:
                    matches.append(current_hierarchy)   # 當前章節匹配，加入結果
                    # 檢查子章節是否也匹配
                    if subchapters:
                        matches.extend(find_sections(page_number, subchapters, current_hierarchy))
            
            return matches
        
        sections = find_sections(page_number, toc, parent_hierarchy)
        if not sections:
            sections = [('Root',)]
        return sections


    def read_pages(self, file_path) -> list[str]:
        """
        Reads a PDF file from the given file into a list.
        
        Args:
            file_path (str): The absolute file path.
        Returns:
            list: A list of texts, including page content, table explanations, and image descriptions. The items in the list correspond to the page order.
        """
        
        pdf_import = PdfImport(file_path)
        return pdf_import.extract_content()
        # return pdf_import.extract_pages()
        # Example of return.
        # return [
        #     '104 年全國各縣市焚化底渣產量約占焚化量之 15%。',
        #     '環境部已提供經費補助，鼓勵縣市政府進行分選後供為營建替代級配材料再利用。',
        #     '垃圾焚化廠焚化底渣再利用管理方式：此公告內容係針對底渣之再利用機構、產品分類、用途及使用地點進行管理要求。',
        # ]


    def _extract_facts(self, page_content):
        messages = [
        {"role": "system", "content": """You are a helpful assistant that extracts nouns, noun phrases, gerunds (verbs 
used as nouns), time, the quantity with units, the content inside parentheses, including the list inside the parentheses, 
and multi-word entities, including adjectives. Avoid extracting simple verbs or be verbs. Ensure that all 
proper nouns, including names (first names, last names, etc.) with modifiers, are included. Return the extracted entities in the same language 
as the article. For example:
        
Example 1:
Text: "Taiwan is an island located in East Asia with diverse natural landscapes and a rich history and culture."
Output: {"facts": ["Taiwan", "island", "East Asia", "diverse natural landscapes", "rich history and culture"]}

Example 2:
Text: "Taipei is the capital of Taiwan and one of its busiest cities, with famous attractions such as Taipei 101 and the 
National Palace Museum."
Output: {"facts": ["Taipei", "capital of Taiwan", "busiest cities", "famous attractions", "Taipei 101", "National Palace Museum"]}

Example 3:
Text: "The annual amount of general waste to be processed is approximately 4 million tons, of which about 3.5 million tons consists of materials (such as paper, non-synthetic fibers/fabrics, wood, bamboo, grass, leaves, etc.), which match the characteristics of biomass."
Output: {"facts": ["general waste", "4 million tons", "3.5 million tons", "paper", "non-synthetic fibers", "fabrics", "wood", "bamboo", "grass", "leaves", "biomass characteristics"]}

Example 4:
Text: "Taiwan is also known for its night market culture, including famous ones like Shilin Night Market and Raohe Street 
Night Market, which attract visitors from around the world."
Output: {"facts": ["night market culture", "Shilin Night Market", "Raohe Street Night Market", "visitors", "world"]}

Example 5:
Text: "Breath held, Hattie watched him separate himself from the hopefuls and approach the stand."
Output: {"facts": ["Hattie", "hopefuls", "stand"]}
"""},
        {"role": "user", "content": f"""Extract the nouns, gerunds, and long multi-word entities, including adjectives, ensuring that the content or list items inside the parentheses are not ignored. If the content inside the parentheses is a list, separate the items and list them individually. Return only a JSON object with a 'facts' array of strings in the same language as the text:
{page_content}"""
        }
        ]
        
        result = app_helper.load_json(self._ask_llm({
            'messages': messages, 'response_format': {'type': 'json_object'},
        }))
        if not isinstance(result, dict) or not isinstance(result.get('facts'), list):
            raise ValueError("Fact extraction must return a JSON object with a facts array.")
        facts = list(dict.fromkeys(
            fact.strip() for fact in result['facts'] if isinstance(fact, str) and fact.strip()
        ))
        logger.debug(f"facts: {facts[:5]}..")

        return facts


    def _extract_concepts(
        self,
        identified_facts,
        page_content,
        _depth: int = 0,
        _max_depth: int = 3,
    ):
        # 基本保護：空集合或超過深度時直接回傳
        if not identified_facts:
            logger.debug("_extract_concepts: empty identified_facts, return {}")
            return {}

        if _depth >= _max_depth:
            logger.warning(
                "_extract_concepts: reach max_depth=%s, stop recursion. remaining facts: %s",
                _max_depth,
                identified_facts,
            )
            return {}

        prompt = f"""Given the following article:
{page_content}

Please identify the hypernyms (concepts) for each of the following identified facts. Each fact should belong to one or more concepts. Return the result as a JSON dictionary, where the keys are the concepts and the values are lists of facts that belong to each concept.

Identified facts:
{identified_facts}

Note:
- The language of the concepts is the same as the facts and article provided.
- Concepts should be general terms that group related facts.
- Please **do not** return the output in any markdown or code block format, such as ` ```json`.
- Only return the JSON dictionary with no additional formatting.

Example output:
{{
    "Geography": ["Taiwan", "island", "East Asia"],
    "City": ["Taipei", "capital", "cities"],
    "Attraction": ["Taipei 101", "National Palace Museum"],
    "Climate": ["climate", "summers", "winters"],
    "Cultural Aspect": ["night market culture", "Shilin Night Market", "Raohe Street Night Market"]
}}
"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ]
        concepts_text = self._ask_llm({"messages": messages, "response_format": {"type": "json_object"}})
        logger.verbose(f"concepts_text: {concepts_text}")

        concepts_dict = app_helper.load_json(concepts_text)
        if not isinstance(concepts_dict, dict) or any(
            not isinstance(facts, list) or not all(isinstance(fact, str) for fact in facts)
            for facts in concepts_dict.values()
        ):
            raise ValueError("Concept extraction must return a JSON object with lists of facts.")
        logger.debug(f"concepts_dict(depth={_depth}): {concepts_dict}")

        concepted_facts = set(
            item for sublist in concepts_dict.values() for item in sublist
        )

        lost_facts = [a for a in identified_facts if a not in concepted_facts]
        logger.debug(
            "_extract_concepts(depth=%s): identified=%s, concepted=%s, lost=%s",
            _depth,
            len(identified_facts),
            len(concepted_facts),
            len(lost_facts),
        )

        # 只在「集合真的縮小」時才遞迴，避免同一批 facts 一直重跑
        if (
            lost_facts
            and len(lost_facts) < len(identified_facts)
            and _depth + 1 < _max_depth
        ):
            new_concepts_dict = self._extract_concepts(
                lost_facts, page_content, _depth=_depth + 1, _max_depth=_max_depth
            )
            logger.warning(
                "new_concepts_dict(depth=%s): %s", _depth + 1, new_concepts_dict
            )
            concepts_dict.update(new_concepts_dict)
        elif lost_facts:
            logger.warning(
                "_extract_concepts: stop recursion (no contraction or reach limit). "
                "remaining facts not grouped into any concept: %s",
                lost_facts,
            )

        return concepts_dict
        
    
    def _extract_facts_relationship(self, identified_facts, page_content):
        if not identified_facts:
            return [], {}
        
        prompt = f"""Given the following article:
{page_content}

Please identify relationships between the listed facts that are supported by the article.
Return a JSON object with a 'relationships' array. Each entry has 'start_fact', 'relation',
and 'end_fact' string fields. Use the listed fact strings exactly for both endpoints.
Return up to 16 distinct, informative relationships. Avoid repeated or rephrased entries.

Identified facts:
{identified_facts}

Note:
- The language of the relationships is the same as the facts and article provided.
- Relationships should describe how facts are related to each other (e.g., causal, geographical, part-of, etc.).
- Please **do not** return the output in any markdown or code block format, such as ` ```json`.
- Only return the JSON object with no additional formatting.

Example output:
{{"relationships": [
    {{"start_fact": "Taipei", "relation": "is a part of", "end_fact": "Taiwan"}},
    {{"start_fact": "Taipei 101", "relation": "is an attraction in", "end_fact": "Taipei"}}
]}}
"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
        
        fields = ('start_fact', 'relation', 'end_fact')
        response_format = {
            'type': 'json_schema',
            'json_schema': {
                'name': 'extract_relationships',
                'strict': True,
                'schema': {
                    'type': 'object',
                    'properties': {
                        'relationships': {
                            'type': 'array',
                            'maxItems': 16,
                            'items': {
                                'type': 'object',
                                'properties': {field: {'type': 'string'} for field in fields},
                                'required': list(fields),
                                'additionalProperties': False,
                            },
                        },
                    },
                    'required': ['relationships'],
                    'additionalProperties': False,
                },
            },
        }
        params = {'messages': messages, 'response_format': response_format}
        result = app_helper.load_json(self._ask_llm(params))
        if not isinstance(result, dict) or not isinstance(result.get('relationships'), list):
            raise ValueError("Relationship extraction must return a JSON object with a relationships array.")
        fact_pairs = [
            tuple(item[field].strip() for field in fields)
            for item in result['relationships']
            if isinstance(item, dict)
            and all(isinstance(item.get(field), str) and item[field].strip() for field in fields)
        ]
        logger.verbose(f"fact_pairs: {fact_pairs}")

        # Ensure the identified facts are correctly related
        lost_facts = [f for f in identified_facts if not any(f == pair[0] or f == pair[2] for pair in fact_pairs)]
        logger.warning(f"lost_facts: {lost_facts}")
        new_concept_facts = {}
        if lost_facts and len(lost_facts) > 1 and len(lost_facts) < len(identified_facts):
            # If there are lost facts and lost_facts is in contraction, re-run the extraction with the lost facts
            lost_fact_pairs, ncf = self._extract_facts_relationship(lost_facts, page_content)
            fact_pairs.extend(lost_fact_pairs)
            new_concept_facts.update(ncf)

        new_facts = []
        try:
            for fact1, _, fact2 in fact_pairs:
                if not fact1 in identified_facts:
                    new_facts.append(fact1)
                if not fact2 in identified_facts:
                    new_facts.append(fact2)
        except Exception as e:
            logger.exception(e)
                
        if new_facts:
            new_concept_facts = self._extract_concepts(new_facts, page_content)
            logger.warning(f"new_concept_facts: {new_concept_facts}")

        return fact_pairs, new_concept_facts
        
    
    def _pair_sections(self, sections, meta):
        sections = sections[-1]
        logger.verbose(f"pair sections: {sections}, meta: {meta}")
        
        part_of_dict = {'name': 'part_of'}
        triplets = []
        for i in range(len(sections)-1):
            if i == 0:
                structure_dict_0 = {'type': 'document', 'name': sections[i], 'meta': meta}
            else:
                structure_dict_0 = {'type': 'structure', 'name': sections[i]}
            structure_dict_1 = {'type': 'structure', 'name': sections[i+1]}
            triplets.append((structure_dict_1, part_of_dict, structure_dict_0))
            logger.verbose(f"append sections: {(structure_dict_1, part_of_dict, structure_dict_0)}")
            
        return triplets


    def _pair_concepts_to_section(self, sections, concepts):
        """
        Create relationships between concepts and document sections.
        
        Args:
            sections (list): List of document sections
            concepts (list): List of identified concepts
        """
        structure_type = 'document' if len(sections) == 1 else 'structure'
        structure_dict = {'type': structure_type, 'name': sections[-1][-1]}
        include_in_dict = {'name': 'include_in'}
        
        triplets = []
        for concept in concepts:
            concept_dict = {'type': 'concept', 'name': concept}
            triplets.append((concept_dict, include_in_dict, structure_dict))
            
        return triplets


    def _pair_facts_to_concept(self, concept_facts):
        is_a = {'name': 'is_a'}
        
        triplets = []
        for concept, facts in concept_facts.items():
            for fact in facts:
                fact_node = {'type': 'fact', 'name': fact}
                concept_node = {'type': 'concept', 'name': concept}
                triplets.append((fact_node, is_a, concept_node))
                
        return triplets


    def _pair_facts_to_fact(self, fact_pairs, concept_facts, page_content):
        """
        Create relationships between different facts.
        
        Args:
            facts_pairs (list): List of fact pairs to be related
        """
        triplets = []
        for pair in fact_pairs:
            # if len(pair) != 3:
            #     logger.warning(f"Skip for wrong facts relation: {pair}")
            #     continue

            fact1 = pair[0]
            rel = pair[1]
            fact2 = pair[2]
            triplets.append(({'type': 'fact', 'name': fact1}, 
                                {'name': rel}, 
                                {'type': 'fact', 'name': fact2}))
                
        return triplets


    def extract_triplets(self, page_content, sections, meta, label="PDF page") -> list[tuple[dict, dict, dict]]:
        app_helper.report_progress(f"{label} · extracting entities.")
        factes = self._extract_facts(page_content)
        app_helper.report_progress(f"{label} · grouping {len(factes)} entities into concepts.")
        concept_facts = self._extract_concepts(factes, page_content)
        identified_facts = list(dict.fromkeys(fact for facts in concept_facts.values() for fact in facts))
        
        logger.debug(f"identified_facts: {identified_facts}")
        app_helper.report_progress(f"{label} · extracting relationships from {len(identified_facts)} facts.")
        fact_pairs, new_concept_facts = self._extract_facts_relationship(identified_facts, page_content)
        logger.debug(f"fact_pairs: {fact_pairs}")
        logger.debug(f"new_concept_facts: {new_concept_facts}")
        
        concept_facts.update(new_concept_facts)
        
        triplets = self._pair_sections(sections, meta)
        triplets.extend(self._pair_concepts_to_section(sections, concept_facts.keys()))
        triplets.extend(self._pair_facts_to_concept(concept_facts))
        triplets.extend(self._pair_facts_to_fact(fact_pairs, concept_facts, page_content))
        
        return triplets



    class LlmChat:
        def __init__(self, agent:Agent):
            self.agent = agent


        def __call__(self, message:str):
            messages = [
                {"role": "user", "content": message},
                # {"role": "user", "content": f"{message}\nPlease provide your response in JSON format."}
            ]            
            params = {
                'messages': messages,
            }            
            pcl = TextParcel(params)
            logger.verbose(f"pcl: {pcl}")

            chat_response = self.agent.publish_sync(LlmService.TOPIC_LLM_PROMPT, pcl, timeout=20)
            response = chat_response.content['response']
            logger.verbose(f"response: {response}")
            
            return response


        # def __call__(self, message:str):
        #     pcl = TextParcel({'prompt': message})
        #     logger.verbose(f"pcl: {pcl}")
            
        #     chat_response = self.agent.publish_sync(LlmService.TOPIC_LLM_PROMPT, pcl, timeout=20)
        #     # logger.debug(f"chat_response: {chat_response}")
        #     return chat_response.content['response']



if __name__ == '__main__':
    llm_config = app_helper.config['service']['llm']['ChatGpt']
    if openai_api_key := llm_config.get('openai_api_key'):
        os.environ.setdefault('OPENAI_API_KEY', openai_api_key)
    
    agent = PdfRetriever(app_helper.get_agent_config())
    agent.start_process()
    app_helper.wait_agent(agent)
