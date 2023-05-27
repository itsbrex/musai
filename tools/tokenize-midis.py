"""
MusAI

Author: Nicolás Iglesias
Email: nfiglesias@gmail.com

This file is part of MusAI, a project for generating MIDI music using 
a combination of machine learning algorithms.

Below is a monolitic script that constructs a corpora of tokens ready to be injected 
into the model. Semantical processing, cleanup and sanitization happens here.

MIT License
Copyright (c) [2023] [Nicolás Iglesias]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import os
import re
import argparse
from loguru import logger
from pathlib import Path
from miditok import REMIPlus, MMM
from miditok.constants import ADDITIONAL_TOKENS, BEAT_RES, INSTRUMENT_CLASSES
from miditok.utils import merge_tracks_per_class, merge_same_program_tracks, get_midi_programs
from miditoolkit import MidiFile
from tqdm import tqdm

# initialize variables
TOKENS_PATH = '/home/nico/data/ai/models/midi/mix'
MIDIS_PATH = '/home/nico/data/midis/MIDI'
TOKEN_PARAMS_NAME = 'token_params.cfg'
TOKEN_PARAMS_PATH = Path(f'{TOKENS_PATH}/{TOKEN_PARAMS_NAME}')

PITCH_RANGE = range(21, 109)
CLASSES_PERCUSSION = [1, 14, 16]
CLASSES_SYNTHS = [10, 11]
CLASSES_STRINGS = [5, 6]
CLASSES_GUITAR_BASS = [3, 4]
CLASS_REED = [8, 9]
CLASS_EFFECTS = [12, 15]
BINS_VELOCITY = (24)
BINS_TEMPO = (24)

TOKENIZER_ALGOS = ['REMI', 'MMM']

# parse command line arguments
arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('-t', '--tokens_path', default=TOKENS_PATH,
                        help='The output path were tokens are saved', type=str)
arg_parser.add_argument('-m', '--midis_path', default=MIDIS_PATH,
                        help='The path where MIDI files can be located', type=str)
arg_parser.add_argument('-g', '--midis_glob', default='*mix*.mid',
                        help='The glob pattern used to locate MIDI files', type=str)
arg_parser.add_argument('-b', '--bpe', help='Applies BPE to the corpora of tokens',
                        action='store_true', default=True)
arg_parser.add_argument('-p', '--process', help='Extracts tokens from the MIDI files',
                        action='store_true', default=False)
arg_parser.add_argument('-s', '--semantical', help='Analyze corpora and process semantical grouping',
                        action='store_true', default=False)
arg_parser.add_argument('-a', '--algo', help='Tokenization algorithm',
                        choices=TOKENIZER_ALGOS, default='MMM', type=str)
args = arg_parser.parse_args()

# initialize logger
logger.add('tokenizer_errors_{time}.log', delay=True,
           backtrace=True, diagnose=True, level='ERROR', rotation='10 MB')

# define some functions


def get_collection():
    """Pre-process and retrieves a collection of MIDI files, ready for tokenization.

    :return: A dictionary containing a set of {'midi': ..., 'programs': ..., 'path': ...} 
            for each MIDI file in the collection.
    :rtype: dict
    """
    MIDI_COLLECTION = {}
    MIDI_FILE_PATHS = list(Path(args.midis_path).glob(args.midis_glob))

    logger.info(
        'Processing collection: {coll_size} MIDI files', coll_size=len(MIDI_FILE_PATHS))

    for MIDI_PATH in tqdm(MIDI_FILE_PATHS):
        try:
            MIDI_NAME = re.sub(
                r'[^0-9a-z_]{1,}', '_', str.lower(os.path.basename(MIDI_PATH)))
            midi = MidiFile(MIDI_PATH)
            programs = get_midi_programs(midi)

            if midi.ticks_per_beat < max(BEAT_RES.values()) * 4:
                continue

            # remove unwanted tracks
            for cls in CLASS_EFFECTS:
                programs_to_delete = list(
                    INSTRUMENT_CLASSES[cls]['program_range'])

            for i in range(0, len(midi.instruments)):
                if midi.instruments[i].program in programs_to_delete:
                    del midi.instruments[i]

            # merge percussion/drums
            merge_tracks_per_class(midi, CLASSES_PERCUSSION)

            # merge synths
            merge_tracks_per_class(midi, CLASSES_SYNTHS)

            # merge strings
            merge_tracks_per_class(midi, CLASSES_STRINGS)

            # merge guitar & bass
            merge_tracks_per_class(midi, CLASSES_GUITAR_BASS)

            # merge_same_program_tracks(midi.instruments)

            MIDI_COLLECTION[MIDI_NAME] = {
                'midi': midi,
                'programs': programs,
                'path': MIDI_PATH
            }
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(e)

    return MIDI_COLLECTION


def get_tokenizer(params=None):
    """Returns a tokenizer.

    :param params: Path to a token_params.cfg file for preloading, defaults to None
    :type params: str, optional
    :return: A MMM or REMIPlus tokenizer.
    :rtype: MIDITokenizer
    """
    if args.algo not in TOKENIZER_ALGOS:
        raise 'Invalid tokenization algorithm'

    additional_tokens = ADDITIONAL_TOKENS
    additional_tokens['Chord'] = True
    additional_tokens['TimeSignature'] = True
    additional_tokens['Program'] = True
    additional_tokens['nb_tempos'] = BINS_TEMPO
    tokenizer = None

    if args.algo == 'REMI':
        tokenizer = REMIPlus(pitch_range=PITCH_RANGE,
                             additional_tokens=additional_tokens,
                             nb_velocities=BINS_VELOCITY,
                             params=params)
    elif args.algo == 'MMM':
        tokenizer = MMM(pitch_range=PITCH_RANGE,
                        additional_tokens=additional_tokens,
                        nb_velocities=BINS_VELOCITY,
                        params=params)

    logger.info('Tokenizer initialized. Using {algo}', algo=args.algo)

    return tokenizer

# begin program


if args.process:
    # initializes tokenizer
    tokenizer = get_tokenizer()
    midi_collection = get_collection()

    logger.info('Processing tokenization: {collection_size} documents', collection_size=len(
        midi_collection.items()))

    Path(args.tokens_path).mkdir(parents=True, exist_ok=True)

    for midi_name, midi_doc in tqdm(midi_collection.items()):
        try:
            midi = midi_doc['midi']
            programs = midi_doc['programs']

            tokens = tokenizer.midi_to_tokens(
                midi, apply_bpe_if_possible=args.bpe)

            tokenizer.save_tokens(
                tokens, f'{args.tokens_path}/{midi_name}.json', programs=programs)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(e)

    logger.info('Vocab size (no BPE): {vocab_size}',
                vocab_size=len(tokenizer.vocab))
    logger.info('Saving params...')

    """ !IMPORTANT always store the _vocab_base when saving params. 
    Order of keys in the vocab may differ in a new instance of a preloaded tokenizer. """
    tokenizer.save_params(
        f'{args.tokens_path}/{TOKEN_PARAMS_NAME}', {'_vocab_base': tokenizer.vocab})

if args.bpe:
    # Constructs the vocabulary with BPE, from the tokenized files
    tokens_bpe_path = f'{args.tokens_path}/bpe'
    token_files_paths = Path(args.tokens_path).glob(f'{args.midis_glob}.json')

    Path(tokens_bpe_path).mkdir(parents=True, exist_ok=True)

    if not args.process:
        tokenizer = get_tokenizer(
            params=f'{args.tokens_path}/{TOKEN_PARAMS_NAME}')

    logger.info('Learning BPE from vocab size {vocab_size}...', vocab_size=len(
        tokenizer.vocab))
    tokenizer.learn_bpe(
        vocab_size=int(len(tokenizer.vocab)*1.25),
        tokens_paths=token_files_paths,
        start_from_empty_voc=False,
    )

    # Converts the tokenized musics into tokens with BPE
    logger.info('Applying BPE...')
    tokenizer.apply_bpe_to_dataset(args.tokens_path, tokens_bpe_path)

    logger.info('Saving params with BPE applied...')
    tokenizer.save_params(f'{tokens_bpe_path}/{TOKEN_PARAMS_NAME}')

    logger.info('Vocab size (BPE): {vocab_size}',
                vocab_size=len(tokenizer.vocab))
