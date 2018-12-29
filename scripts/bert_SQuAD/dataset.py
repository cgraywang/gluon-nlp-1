# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors and DMLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""BERT datasets."""
import collections
import json
import multiprocessing as mp
import time

import numpy as np
from mxnet import context, nd
from mxnet.gluon.data import SimpleDataset


class SquadExample(object):
    """A single training/test example for SQuAD question.

       For examples without an answer, the start and end position are -1.
    """

    def __init__(self,
                 qas_id,
                 question_text,
                 doc_tokens,
                 example_id,
                 orig_answer_text=None,
                 start_position=None,
                 end_position=None,
                 is_impossible=False):
        self.qas_id = qas_id
        self.question_text = question_text
        self.doc_tokens = doc_tokens
        self.orig_answer_text = orig_answer_text
        self.start_position = start_position
        self.end_position = end_position
        self.is_impossible = is_impossible
        self.example_id = example_id


_transform = None


def preprocess(example):
    global _transform
    feature = _transform(example)
    return feature


def preprocess_dataset(dataset, transform):
    global _transform
    _transform = transform
    start = time.time()

    with mp.Pool(8) as pool:
        dataset_transform = []
        for data in pool.map(preprocess, dataset):
            dataset_transform.extend(data)

        dataset = SimpleDataset(dataset_transform)
    end = time.time()
    print(end-start)
    return dataset


class SquadFeature(object):
    def __init__(self,
                 example_id,
                 qas_id,
                 doc_tokens,
                 doc_span_index,
                 tokens,
                 token_to_orig_map,
                 token_is_max_context,
                 input_ids,
                 valid_length,
                 segment_ids,
                 start_position,
                 end_position,
                 is_impossible):
        self.example_id = example_id
        self.qas_id = qas_id
        self.doc_tokens = doc_tokens
        self.doc_span_index = doc_span_index
        self.tokens = tokens
        self.token_to_orig_map = token_to_orig_map
        self.token_is_max_context = token_is_max_context
        self.input_ids = input_ids
        self.valid_length = valid_length
        self.segment_ids = segment_ids
        self.start_position = start_position
        self.end_position = end_position
        self.is_impossible = is_impossible


class SQuAD(SimpleDataset):
    """Stanford Question Answering Dataset (SQuAD) - reading comprehension dataset.

    From
    https://rajpurkar.github.io/SQuAD-explorer/

    License: CreativeCommons BY-SA 4.0

    The original data format is json, which has multiple contexts (a context is a paragraph of text
    from which questions are drawn). For each context there are multiple questions, and for each of
    these questions there are multiple (usually 3) answers.

    This class loads the json and flattens it to question dataset.
    Number of records in the dataset is equal to number of questions in json file.


    Parameters
    ----------
    filename : str
        SQuAD json file path.
    is_training : bool, default True
        Whether to run training.
    version_2 : bool, default False
        If true, the SQuAD examples contain some that do not have an answer.
    """

    def __init__(self, filename, is_training=True, version_2=False):
        self.input_file = filename
        self.is_training = is_training
        self.version_2 = version_2
        super(SQuAD, self).__init__(self._read())

    def _read(self):
        """Read a SQuAD json file into a list of SquadExample."""
        with open(self.input_file, 'r') as reader:
            input_data = json.load(reader)['data']

        def is_whitespace(c):
            if c == ' ' or c == '\t' or c == '\r' or c == '\n' or ord(
                    c) == 0x202F:
                return True
            return False

        examples = []
        example_id = 0
        for entry in input_data:
            for paragraph in entry['paragraphs']:
                paragraph_text = paragraph['context']
                doc_tokens = []
                char_to_word_offset = []
                prev_is_whitespace = True
                for c in paragraph_text:
                    if is_whitespace(c):
                        prev_is_whitespace = True
                    else:
                        if prev_is_whitespace:
                            doc_tokens.append(c)
                        else:
                            doc_tokens[-1] += c
                        prev_is_whitespace = False
                    char_to_word_offset.append(len(doc_tokens) - 1)

                for qa in paragraph['qas']:
                    qas_id = qa['id']
                    question_text = qa['question']
                    start_position = None
                    end_position = None
                    orig_answer_text = None
                    is_impossible = False
                    if self.is_training:

                        if self.version_2:
                            is_impossible = qa['is_impossible']
                        if (len(qa['answers']) != 1) and (not is_impossible):
                            raise ValueError(
                                'For training, each question should have exactly 1 answer.'
                            )
                        if not is_impossible:
                            answer = qa['answers'][0]
                            orig_answer_text = answer['text']
                            answer_offset = answer['answer_start']
                            answer_length = len(orig_answer_text)
                            start_position = char_to_word_offset[answer_offset]
                            end_position = char_to_word_offset[
                                answer_offset + answer_length - 1]
                            # Only add answers where the text can be exactly recovered from the
                            # document. If this CAN'T happen it's likely due to weird Unicode
                            # stuff so we will just skip the example.
                            #
                            # Note that this means for training mode, every example is NOT
                            # guaranteed to be preserved.
                            actual_text = ' '.join(
                                doc_tokens[start_position:(end_position + 1)])
                            cleaned_answer_text = ' '.join(
                                self.whitespace_tokenize(orig_answer_text))
                            if actual_text.find(cleaned_answer_text) == -1:
                                print('Could not find answer: %s vs. %s' %
                                      (actual_text, cleaned_answer_text))
                                continue
                        else:
                            start_position = -1
                            end_position = -1
                            orig_answer_text = ''

                    example = SquadExample(
                        qas_id=qas_id,
                        question_text=question_text,
                        doc_tokens=doc_tokens,
                        example_id=example_id,
                        orig_answer_text=orig_answer_text,
                        start_position=start_position,
                        end_position=end_position,
                        is_impossible=is_impossible)
                    examples.append(example)

                    example_id += 1

        return examples

    def whitespace_tokenize(self, text):
        """Runs basic whitespace cleaning and splitting on a piece of text."""
        text = text.strip()
        if not text:
            return []
        tokens = text.split()
        return tokens


class SQuADTransform(object):
    """Dataset Transformation for BERT-style QA.

    Parameters
    ----------
    tokenizer : BERTTokenizer.
        Tokenizer for the sentences.
    labels : list of int.
        List of all label ids for the classification task.
    max_seq_length : int, default 384
        Maximum sequence length of the sentences.
    doc_stride : int, default 128
        pass
    max_query_length : int, default 64
        pass
    is_training : bool, default True
        Whether to run training.
    """

    def __init__(self,
                 tokenizer,
                 max_seq_length=384,
                 doc_stride=128,
                 max_query_length=64,
                 is_training=True):
        self.tokenizer = tokenizer
        self.max_seq_length = max_seq_length
        self.max_query_length = max_query_length
        self.doc_stride = doc_stride
        self.is_training = is_training

    def _transform(self, example):
        features = []
        query_tokens = self.tokenizer(example.question_text)

        if len(query_tokens) > self.max_query_length:
            query_tokens = query_tokens[0:self.max_query_length]

        tok_to_orig_index = []
        orig_to_tok_index = []
        all_doc_tokens = []
        for (i, token) in enumerate(example.doc_tokens):
            orig_to_tok_index.append(len(all_doc_tokens))
            sub_tokens = self.tokenizer(token)
            for sub_token in sub_tokens:
                tok_to_orig_index.append(i)
                all_doc_tokens.append(sub_token)

        tok_start_position = None
        tok_end_position = None
        if self.is_training and example.is_impossible:
            tok_start_position = -1
            tok_end_position = -1
        if self.is_training and not example.is_impossible:
            tok_start_position = orig_to_tok_index[example.start_position]
            if example.end_position < len(example.doc_tokens) - 1:
                tok_end_position = orig_to_tok_index[example.end_position +
                                                     1] - 1
            else:
                tok_end_position = len(all_doc_tokens) - 1
            (tok_start_position, tok_end_position) = _improve_answer_span(
                all_doc_tokens, tok_start_position, tok_end_position,
                self.tokenizer, example.orig_answer_text)

        # The -3 accounts for [CLS], [SEP] and [SEP]
        max_tokens_for_doc = self.max_seq_length - len(query_tokens) - 3

        # We can have documents that are longer than the maximum sequence length.
        # To deal with this we do a sliding window approach, where we take chunks
        # of the up to our max length with a stride of `doc_stride`.
        _DocSpan = collections.namedtuple(  # pylint: disable=invalid-name
            'DocSpan', ['start', 'length'])
        doc_spans = []
        start_offset = 0
        while start_offset < len(all_doc_tokens):
            length = len(all_doc_tokens) - start_offset
            if length > max_tokens_for_doc:
                length = max_tokens_for_doc
            doc_spans.append(_DocSpan(start=start_offset, length=length))
            if start_offset + length == len(all_doc_tokens):
                break
            start_offset += min(length, self.doc_stride)

        for (doc_span_index, doc_span) in enumerate(doc_spans):
            tokens = []
            token_to_orig_map = {}
            token_is_max_context = {}
            segment_ids = []
            tokens.append('[CLS]')
            segment_ids.append(0)
            for token in query_tokens:
                tokens.append(token)
                segment_ids.append(0)
            tokens.append('[SEP]')
            segment_ids.append(0)

            for i in range(doc_span.length):
                split_token_index = doc_span.start + i
                token_to_orig_map[len(
                    tokens)] = tok_to_orig_index[split_token_index]

                is_max_context = _check_is_max_context(
                    doc_spans, doc_span_index, split_token_index)
                token_is_max_context[len(tokens)] = is_max_context
                tokens.append(all_doc_tokens[split_token_index])
                segment_ids.append(1)
            tokens.append('[SEP]')
            segment_ids.append(1)

            input_ids = self.tokenizer.convert_tokens_to_ids(tokens)

            # The mask has 1 for real tokens and 0 for padding tokens. Only real
            # tokens are attended to.
            valid_length = len(input_ids)

            # Zero-pad up to the sequence length.
            while len(input_ids) < self.max_seq_length:
                input_ids.append(0)
                segment_ids.append(0)

            assert len(input_ids) == self.max_seq_length
            assert len(segment_ids) == self.max_seq_length

            start_position = 0
            end_position = 0
            if self.is_training and not example.is_impossible:
                # For training, if our document chunk does not contain an annotation
                # we throw it out, since there is nothing to predict.
                doc_start = doc_span.start
                doc_end = doc_span.start + doc_span.length - 1
                out_of_span = False
                if not (tok_start_position >= doc_start
                        and tok_end_position <= doc_end):
                    out_of_span = True
                if out_of_span:
                    start_position = 0
                    end_position = 0
                else:
                    doc_offset = len(query_tokens) + 2
                    start_position = tok_start_position - doc_start + doc_offset
                    end_position = tok_end_position - doc_start + doc_offset

            if self.is_training and example.is_impossible:
                start_position = 0
                end_position = 0
            features.append(SquadFeature(example_id=example.example_id,
                                         qas_id=example.qas_id,
                                         doc_tokens=example.doc_tokens,
                                         doc_span_index=doc_span_index,
                                         tokens=tokens,
                                         token_to_orig_map=token_to_orig_map,
                                         token_is_max_context=token_is_max_context,
                                         input_ids=input_ids,
                                         valid_length=valid_length,
                                         segment_ids=segment_ids,
                                         start_position=start_position,
                                         end_position=end_position,
                                         is_impossible=example.is_impossible))
        return features

    def __call__(self, example):
        examples = self._transform(example)
        features = []

        for _example in examples:
            feature = []
            feature.append(_example.example_id)
            feature.append(_example.input_ids)
            feature.append(_example.segment_ids)
            feature.append(_example.valid_length)
            feature.append(_example.start_position)
            feature.append(_example.end_position)
            features.append(feature)

        return features


def bert_qa_batchify_fn(data):
    """Collate data into batch."""
    def batchify_fn(data):
        data = np.asarray(data)
        return nd.array(data, dtype=data.dtype, ctx=context.Context('cpu_shared', 0))

    data = zip(*data)
    return [batchify_fn(i) for i in data]


def _improve_answer_span(doc_tokens, input_start, input_end, tokenizer,
                         orig_answer_text):
    """Returns tokenized answer spans that better match the annotated answer."""

    # The SQuAD annotations are character based. We first project them to
    # whitespace-tokenized words. But then after WordPiece tokenization, we can
    # often find a "better match". For example:
    #
    #   Question: What year was John Smith born?
    #   Context: The leader was John Smith (1895-1943).
    #   Answer: 1895
    #
    # The original whitespace-tokenized answer will be "(1895-1943).". However
    # after tokenization, our tokens will be "( 1895 - 1943 ) .". So we can match
    # the exact answer, 1895.
    #
    # However, this is not always possible. Consider the following:
    #
    #   Question: What country is the top exporter of electornics?
    #   Context: The Japanese electronics industry is the lagest in the world.
    #   Answer: Japan
    #
    # In this case, the annotator chose "Japan" as a character sub-span of
    # the word "Japanese". Since our WordPiece tokenizer does not split
    # "Japanese", we just use "Japanese" as the annotation. This is fairly rare
    # in SQuAD, but does happen.
    tok_answer_text = ' '.join(tokenizer(orig_answer_text))

    for new_start in range(input_start, input_end + 1):
        for new_end in range(input_end, new_start - 1, -1):
            text_span = ' '.join(doc_tokens[new_start:(new_end + 1)])
            if text_span == tok_answer_text:
                return (new_start, new_end)

    return (input_start, input_end)


def _check_is_max_context(doc_spans, cur_span_index, position):
    """Check if this is the 'max context' doc span for the token."""

    # Because of the sliding window approach taken to scoring documents, a single
    # token can appear in multiple documents. E.g.
    #  Doc: the man went to the store and bought a gallon of milk
    #  Span A: the man went to the
    #  Span B: to the store and bought
    #  Span C: and bought a gallon of
    #  ...
    #
    # Now the word 'bought' will have two scores from spans B and C. We only
    # want to consider the score with "maximum context", which we define as
    # the *minimum* of its left and right context (the *sum* of left and
    # right context will always be the same, of course).
    #
    # In the example the maximum context for 'bought' would be span C since
    # it has 1 left context and 3 right context, while span B has 4 left context
    # and 0 right context.
    best_score = None
    best_span_index = None
    for (span_index, doc_span) in enumerate(doc_spans):
        end = doc_span.start + doc_span.length - 1
        if position < doc_span.start:
            continue
        if position > end:
            continue
        num_left_context = position - doc_span.start
        num_right_context = end - position
        score = min(num_left_context, num_right_context) + \
            0.01 * doc_span.length
        if best_score is None or score > best_score:
            best_score = score
            best_span_index = span_index

    return cur_span_index == best_span_index
