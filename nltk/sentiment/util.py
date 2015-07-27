# coding: utf-8
#
# Natural Language Toolkit: Sentiment Analyzer
#
# Copyright (C) 2001-2015 NLTK Project
# Author: Pierpaolo Pantone <24alsecondo@gmail.com>
# URL: <http://nltk.org/>
# For license information, see LICENSE.TXT

"""
Utility methods for Sentiment Analysis.
"""

from copy import deepcopy
import codecs
import csv
import json
import pickle
import random
import re
import sys
import time
try:
    import matplotlib.pyplot as plt
except ImportError:
    import warnings
    warnings.warn("matplotlib not installed. Graph generation not available.")

import nltk
from nltk.corpus import CategorizedPlaintextCorpusReader
from nltk.data import load
from nltk.tokenize.casual import EMOTICON_RE
from nltk.twitter.util import outf_writer_compat, extract_fields

#////////////////////////////////////////////////////////////
#{ Regular expressions
#////////////////////////////////////////////////////////////

# Regular expression for negation by Christopher Potts
NEGATION = r"""
    (?:
        ^(?:never|no|nothing|nowhere|noone|none|not|
            havent|hasnt|hadnt|cant|couldnt|shouldnt|
            wont|wouldnt|dont|doesnt|didnt|isnt|arent|aint
        )$
    )
    |
    n't"""

NEGATION_RE = re.compile(NEGATION, re.VERBOSE)

CLAUSE_PUNCT = r'^[.:;!?]$'
CLAUSE_PUNCT_RE = re.compile(CLAUSE_PUNCT)

# Happy and sad emoticons

HAPPY = {
    ':-)', ':)', ';)', ':o)', ':]', ':3', ':c)', ':>', '=]', '8)', '=)', ':}',
    ':^)', ':-D', ':D', '8-D', '8D', 'x-D', 'xD', 'X-D', 'XD', '=-D', '=D',
    '=-3', '=3', ':-))', ":'-)", ":')", ':*', ':^*', '>:P', ':-P', ':P', 'X-P',
    'x-p', 'xp', 'XP', ':-p', ':p', '=p', ':-b', ':b', '>:)', '>;)', '>:-)',
    '<3'
    }

SAD = {
    ':L', ':-/', '>:/', ':S', '>:[', ':@', ':-(', ':[', ':-||', '=L', ':<',
    ':-[', ':-<', '=\\', '=/', '>:(', ':(', '>.<', ":'-(", ":'(", ':\\', ':-c',
    ':c', ':{', '>:\\', ';('
    }

def timer(method):
    """
    A timer decorator to measure execution performance of methods.
    """
    def timed(*args, **kw):
        start = time.time()
        result = method(*args, **kw)
        end = time.time()
        tot_time = end - start
        hours = int(tot_time / 3600)
        mins = int((tot_time / 60) % 60)
        # in Python 2.x round() will return a float, so we convert it to int
        secs = int(round(tot_time % 60))
        if hours == 0 and mins == 0 and secs < 10:
            print('[TIMER] {}(): {:.3f} seconds'.format(method.__name__, tot_time))
        else:
            print('[TIMER] {}(): {}h {}m {}s'.format(method.__name__, hours, mins, secs))
        return result
    return timed

#////////////////////////////////////////////////////////////
#{ Feature extractor functions
#////////////////////////////////////////////////////////////
"""
Feature extractor functions are declared outside the SentimentAnalyzer class.
Users should have the possibility to create their own feature extractors
without modifying SentimentAnalyzer.
"""

def extract_unigram_feats(document, unigrams, handle_negation=False):
    """
    Populate a dictionary of unigram features, reflecting the presence/absence in
    the document of each of the tokens in `unigrams`.

    :param document: a list of words/tokens.
    :param unigrams: a list of words/tokens whose presence/absence has to be
        checked in `document`.
    :param handle_negation: if `handle_negation == True` apply `mark_negation`
        method to `document` before checking for unigram presence/absence.
    :return: a dictionary of unigram features {unigram : boolean}.

    >>> words = ['ice', 'police', 'riot']
    >>> document = 'ice is melting due to global warming'.split()
    >>> sorted(extract_unigram_feats(document, words).items())
    [('contains(ice)', True), ('contains(police)', False), ('contains(riot)', False)]
    """
    features = {}
    if handle_negation:
        document = mark_negation(document)
    for word in unigrams:
        features['contains({})'.format(word)] = word in set(document)
    return features

def extract_bigram_feats(document, bigrams):
    """
    Populate a dictionary of bigram features, reflecting the presence/absence in
    the document of each of the tokens in `bigrams`. This extractor function only
    considers contiguous bigrams obtained by `nltk.bigrams`.

    :param document: a list of words/tokens.
    :param unigrams: a list of bigrams whose presence/absence has to be
        checked in `document`.
    :return: a dictionary of bigram features {bigram : boolean}.

    >>> bigrams = [('global', 'warming'), ('police', 'prevented'), ('love', 'you')]
    >>> document = 'ice is melting due to global warming'.split()
    >>> sorted(extract_bigram_feats(document, bigrams).items())
    [('contains(global - warming)', True), ('contains(love - you)', False),
    ('contains(police - prevented)', False)]
    """
    features = {}
    for bigr in bigrams:
        features['contains({} - {})'.format(bigr[0], bigr[1])] = bigr in nltk.bigrams(document)
    return features

#////////////////////////////////////////////////////////////
#{ Helper Functions
#////////////////////////////////////////////////////////////

def mark_negation(document, double_neg_flip=False, shallow=False):
    '''
    Append _NEG suffix to words that appear in the scope between a negation
    and a punctuation mark.

    :param document: a list of words/tokens, or a tuple (words, label).
    :param shallow: if True, the method will modify the original document in place.
    :param double_neg_flip: if True, double negation is considered affirmation
        (we activate/deactivate negation scope everytime we find a negation).
    :return: if `shallow == True` the method will modify the original document
        and return it. If `shallow == False` the method will return a modified
        document, leaving the original unmodified.

    >>> sent = "I didn't like this movie . It was bad .".split()
    >>> mark_negation(sent)
    ['I', "didn't", 'like_NEG', 'this_NEG', 'movie_NEG', '.', 'It', 'was', 'bad', '.']

    '''
    if not shallow:
        document = deepcopy(document)
    # check if the document is labeled. If so, do not consider the label.
    labeled = document and isinstance(document[0], (tuple, list))
    if labeled:
        doc = document[0]
    else:
        doc = document
    neg_scope = False
    for i, word in enumerate(doc):
        if NEGATION_RE.search(word):
            if not neg_scope or (neg_scope and double_neg_flip):
                neg_scope = not neg_scope
                continue
            else:
                doc[i] += '_NEG'
        elif neg_scope and CLAUSE_PUNCT_RE.search(word):
            neg_scope = not neg_scope
        elif neg_scope and not CLAUSE_PUNCT_RE.search(word):
            doc[i] += '_NEG'

    return document

def output_markdown(filename, **kwargs):
    """
    Write the output of an analysis to a file.
    """
    with codecs.open(filename, 'at') as outfile:
        text = '\n*** \n\n'
        text += '{} \n\n'.format(time.strftime("%d/%m/%Y, %H:%M"))
        for k in sorted(kwargs):
            text += '  - **{}:** {} \n'.format(k, kwargs[k])
        outfile.write(text)

def save_file(content, filename):
    """
    Store `content` in `filename`. Can be used to store a SentimentAnalyzer.
    """
    print("Saving", filename)
    with codecs.open(filename, 'wb') as storage_file:
        # The protocol=2 parameter is for python2 compatibility
        pickle.dump(content, storage_file, protocol=2)

def split_train_test(all_instances, n=None):
    """
    Randomly split `n` instances of the dataset into train and test sets.

    :param all_instances: a list of instances (e.g. documents) that will be split.
    :param n: the number of instances to consider (in case we want to use only a
        subset).
    :return: two lists of instances. Train set is 8/10 of the total and test set
        is 2/10 of the total.
    """
    random.seed(12345)
    random.shuffle(all_instances)
    if not n or n > len(all_instances):
        n = len(all_instances)
    train_set = all_instances[:int(.8*n)]
    test_set = all_instances[int(.8*n):n]

    return train_set, test_set

def _show_plot(x_values, y_values, x_labels=None, y_labels=None):
    plt.locator_params(axis='y', nbins=3)
    axes = plt.axes()
    axes.yaxis.grid()
    plt.plot(x_values, y_values, 'ro', color='red')
    plt.ylim(ymin=-1.2, ymax=1.2)
    plt.tight_layout(pad=5)
    if x_labels:
        plt.xticks(x_values, x_labels, rotation='vertical')
    if y_labels:
        plt.yticks([-1, 0, 1], y_labels, rotation='horizontal')
    # Pad margins so that markers are not clipped by the axes
    plt.margins(0.2)
    plt.show()

#////////////////////////////////////////////////////////////
#{ Parsing and conversion functions
#////////////////////////////////////////////////////////////

def json2csv_preprocess(json_file, outfile, fields, encoding='utf8', errors='replace',
            gzip_compress=False, skip_retweets=True, skip_tongue_tweets=True,
            skip_ambiguous_tweets=True, strip_off_emoticons=True, remove_duplicates=True,
            limit=None):
    """
    Convert json file to csv file, preprocessing each row to obtain a suitable
    dataset for tweets Semantic Analysis.

    :param json_file: the original json file containing tweets.
    :param outfile: the output csv filename.
    :param fields: a list of fields that will be extracted from the json file and
        kept in the output csv file.
    :param encoding: the encoding of the files.
    :param errors: the error handling strategy for the output writer.
    :param gzip_compress: if True, create a compressed GZIP file.

    :param skip_retweets: if True, remove retweets.
    :param skip_tongue_tweets: if True, remove tweets containing ":P" and ":-P"
        emoticons.
    :param skip_ambiguous_tweets: if True, remove tweets containing both happy
        and sad emoticons.
    :param strip_off_emoticons: if True, strip off emoticons from all tweets.
    :param remove_duplicates: if True, remove tweets appearing more than once.
    :param limit: an integer to set the number of tweets to convert. After the
        limit is reached the conversion will stop. It can be useful to create
        subsets of the original tweets json data.
    """
    with codecs.open(json_file, encoding=encoding) as fp:
        (writer, outf) = outf_writer_compat(outfile, encoding, errors, gzip_compress)
        # write the list of fields as header
        writer.writerow(fields)

        if remove_duplicates == True:
            tweets_cache = []
        i = 0
        for line in fp:
            tweet = json.loads(line)
            row = extract_fields(tweet, fields)
            try:
                text = row[fields.index('text')]
                # Remove retweets
                if skip_retweets == True:
                    if re.search(r'\bRT\b', text):
                        continue
                # Remove tweets containing ":P" and ":-P" emoticons
                if skip_tongue_tweets == True:
                    if re.search(r'\:\-?P\b', text):
                        continue
                # Remove tweets containing both happy and sad emoticons
                if skip_ambiguous_tweets == True:
                    all_emoticons = EMOTICON_RE.findall(text)
                    if all_emoticons:
                        if (set(all_emoticons) & HAPPY) and (set(all_emoticons) & SAD):
                            continue
                # Strip off emoticons from all tweets
                if strip_off_emoticons == True:
                    row[fields.index('text')] = re.sub(r'(?!\n)\s+', ' ', EMOTICON_RE.sub('', text))
                # Remove duplicate tweets
                if remove_duplicates == True:
                    if row[fields.index('text')] in tweets_cache:
                        continue
                    else:
                        tweets_cache.append(row[fields.index('text')])
            except ValueError:
                pass
            writer.writerow(row)
            i += 1
            if limit and i >= limit:
                break
        outf.close()

def parse_tweets_set(filename, label, word_tokenizer=None, sent_tokenizer=None,
                     skip_header=True):
    '''
    Parse csv file containing tweets and output data a list of (text, label) tuples.

    :param filename: the input csv filename.
    :param label: the label to be appended to each tweet contained in the csv file.
    :param word_tokenizer: the tokenizer instance that will be used to tokenize
        each sentence into tokens (e.g. WordPunctTokenizer() or BlanklineTokenizer()).
        If no word_tokenizer is specified, tweets will not be tokenized.
    :param sent_tokenizer: the tokenizer that will be used to split each tweet into
        sentences.
    :param skip_header: if True, skip the first line of the csv file (which usually
        contains headers).

    :return: a list of (text, label) tuples.
    '''
    tweets = []
    if not sent_tokenizer:
        sent_tokenizer = load('tokenizers/punkt/english.pickle')

    # If we use Python3.x we can proceed using the 'rt' flag
    if sys.version_info[0] == 3:
        with codecs.open(filename, 'rt') as csvfile:
            reader = csv.reader(csvfile)
            if skip_header == True:
                next(reader, None) # skip the header
            i = 0
            for tweet_id, text in reader:
                # text = text[1]
                i += 1
                sys.stdout.write('Loaded {} tweets\r'.format(i))
                # Apply sentence and word tokenizer to text
                if word_tokenizer:
                    tweet = [w for sent in sent_tokenizer.tokenize(text)
                                       for w in word_tokenizer.tokenize(sent)]
                else:
                    tweet = text
                tweets.append((tweet, label))
    # If we use Python2.x we need to handle encoding problems
    elif sys.version_info[0] < 3:
        with codecs.open(filename) as csvfile:
            reader = csv.reader(csvfile)
            if skip_header == True:
                next(reader, None) # skip the header
            i = 0
            for row in reader:
                unicode_row = [x.decode('utf8') for x in row]
                text = unicode_row[1]
                i += 1
                sys.stdout.write('Loaded {} tweets\r'.format(i))
                # Apply sentence and word tokenizer to text
                if word_tokenizer:
                    tweet = [w.encode('utf8') for sent in sent_tokenizer.tokenize(text)
                                       for w in word_tokenizer.tokenize(sent)]
                else:
                    tweet = text
                tweets.append((tweet, label))
    print("Loaded {} tweets".format(i))
    return tweets

def parse_subjectivity_dataset(filename, word_tokenizer, label=None):
    """
    Parse the Subjectivity Dataset by Pang and Lee.
    """
    with codecs.open(filename, 'rb') as inputfile:
        docs = []
        for line in inputfile:
            tokenized_line = word_tokenizer.tokenize(line.decode('latin-1'))
            docs.append((tokenized_line, label))
    return docs

#////////////////////////////////////////////////////////////
#{ Demos
#////////////////////////////////////////////////////////////

def demo_tweets(trainer):
    '''
    Train and test Naive Bayes classifier on 10000 tweets, tokenized using
    TweetTokenizer.
    Features are composed of:
        - 1000 most frequent unigrams
        - 100 top bigrams (using BigramAssocMeasures.pmi)

    :param trainer: `train` method of a classifier.
    '''
    from nltk.tokenize import TweetTokenizer
    from sentiment_analyzer import SentimentAnalyzer
    from nltk.corpus import twitter_samples, stopwords

    # Different customizations for the TweetTokenizer
    tokenizer = TweetTokenizer(preserve_case=False)
    # tokenizer = TweetTokenizer(preserve_case=True, strip_handles=True)
    # tokenizer = TweetTokenizer(reduce_len=True, strip_handles=True)

    positive_json = twitter_samples.abspath("positive_tweets.json")

    fields = ['id', 'text']
    positive_csv = 'positive_tweets.csv'
    json2csv_preprocess(positive_json, positive_csv, fields, limit=5000)

    negative_json = twitter_samples.abspath("negative_tweets.json")
    negative_csv = 'negative_tweets.csv'
    json2csv_preprocess(negative_json, negative_csv, fields, limit=5000)

    pos_docs = parse_tweets_set(positive_csv, label='pos', word_tokenizer=tokenizer)
    neg_docs = parse_tweets_set(negative_csv, label='neg', word_tokenizer=tokenizer)

    # We separately split subjective and objective instances to keep a balanced
    # uniform class distribution in both train and test sets.
    train_pos_docs, test_pos_docs = split_train_test(pos_docs)
    train_neg_docs, test_neg_docs = split_train_test(neg_docs)

    training_tweets = train_pos_docs+train_neg_docs
    testing_tweets = test_pos_docs+test_neg_docs

    stopwords = stopwords.words('english')
    sa = SentimentAnalyzer()
    all_words = [word for word in sa.all_words(training_tweets) if word.lower() not in stopwords]

    # Add simple unigram word features
    unigram_feats = sa.unigram_word_feats(all_words, top_n=1000)
    sa.add_feat_extractor(extract_unigram_feats, unigrams=unigram_feats)

    # Add bigram collocation features
    bigram_collocs_feats = sa.bigram_collocation_feats([tweet[0] for tweet in training_tweets],
        top_n=100, min_freq=12)
    sa.add_feat_extractor(extract_bigram_feats, bigrams=bigram_collocs_feats)

    training_set = sa.apply_features(training_tweets)
    test_set = sa.apply_features(testing_tweets)

    classifier = sa.train(trainer, training_set)
    # classifier = sa.train(trainer, training_set, max_iter=4)
    try:
        classifier.show_most_informative_features()
    except AttributeError:
        print('Your classifier does not provide a show_most_informative_features() method.')
    accuracy = sa.evaluate(classifier, test_set)
    print('Accuracy:', accuracy)

    extr = [f.__name__ for f in sa.feat_extractors]
    output_markdown('results.md', Dataset='labeled_tweets', Classifier=type(classifier).__name__,
                    Tokenizer=tokenizer.__class__.__name__, Feats=extr, Accuracy=accuracy,
                    Notes='Remove stopwords')

def demo_movie_reviews(trainer):
    '''
    Train classifier on all instances of the Movie Reviews dataset.
    The corpus has been preprocessed using the default sentence tokenizer and
    WordPunctTokenizer.
    Features are composed of:
        - 1000 most frequent unigrams

    :param trainer: `train` method of a classifier.
    '''
    from nltk.corpus import movie_reviews
    from sentiment_analyzer import SentimentAnalyzer

    pos_docs = [(list(movie_reviews.words(pos_id)), 'pos') for pos_id in movie_reviews.fileids('pos')]
    neg_docs = [(list(movie_reviews.words(neg_id)), 'neg') for neg_id in movie_reviews.fileids('neg')]

    # We separately split positive and negative instances to keep a balanced
    # uniform class distribution in both train and test sets.
    train_pos_docs, test_pos_docs = split_train_test(pos_docs)
    train_neg_docs, test_neg_docs = split_train_test(neg_docs)

    training_docs = train_pos_docs+train_neg_docs
    testing_docs = test_pos_docs+test_neg_docs

    sa = SentimentAnalyzer()
    all_words = sa.all_words(training_docs)

    # Add simple unigram word features
    unigram_feats = sa.unigram_word_feats(all_words, min_freq=4)
    sa.add_feat_extractor(extract_unigram_feats, unigrams=unigram_feats)

    # Apply features to obtain a feature-value representation of our datasets
    training_set = sa.apply_features(training_docs)
    test_set = sa.apply_features(testing_docs)

    classifier = sa.train(trainer, training_set)
    try:
        classifier.show_most_informative_features()
    except AttributeError:
        print('Your classifier does not provide a show_most_informative_features() method.')
    accuracy = sa.evaluate(classifier, test_set)
    print('Accuracy:', accuracy)

    extr = [f.__name__ for f in sa.feat_extractors]
    output_markdown('results.md', Dataset='Movie_reviews', Classifier=type(classifier).__name__,
                    Tokenizer='WordPunctTokenizer', Feats=extr, Accuracy=accuracy)

def demo_subjectivity(trainer, save_analyzer=False):
    """
    Train and test a classifier on instances of the Subjective Dataset by Pang and
    Lee. The dataset is made of 5000 subjective and 5000 objective sentences.
    All tokens (words and punctuation marks) are separated by a whitespace, so
    we use the basic WhitespaceTokenizer to parse the data.

    :param trainer: `train` method of a classifier.
    """

    from sentiment_analyzer import SentimentAnalyzer
    from nltk.tokenize import regexp

    word_tokenizer = regexp.WhitespaceTokenizer()

    subj_data = '/home/fievelk/nltk_data/corpora/rotten_imdb/quote.tok.gt9_subj.5000'
    subj_docs = parse_subjectivity_dataset(subj_data, word_tokenizer=word_tokenizer,
                                           label='subj')
    obj_data = '/home/fievelk/nltk_data/corpora/rotten_imdb/plot.tok.gt9_obj.5000'
    obj_docs = parse_subjectivity_dataset(obj_data, word_tokenizer=word_tokenizer,
                                          label='obj')

    # We separately split subjective and objective instances to keep a balanced
    # uniform class distribution in both train and test sets.
    train_subj_docs, test_subj_docs = split_train_test(subj_docs)
    train_obj_docs, test_obj_docs = split_train_test(obj_docs)

    training_docs = train_subj_docs+train_obj_docs
    testing_docs = test_subj_docs+test_obj_docs

    sentim_analyzer = SentimentAnalyzer()
    all_words_neg = sentim_analyzer.all_words([mark_negation(doc) for doc in training_docs])

    # Add simple unigram word features handling negation
    unigram_feats = sentim_analyzer.unigram_word_feats(all_words_neg, min_freq=4)
    sentim_analyzer.add_feat_extractor(extract_unigram_feats, unigrams=unigram_feats)

    # Apply features to obtain a feature-value representation of our datasets
    training_set = sentim_analyzer.apply_features(training_docs)
    test_set = sentim_analyzer.apply_features(testing_docs)

    classifier = sentim_analyzer.train(trainer, training_set)
    try:
        classifier.show_most_informative_features()
    except AttributeError:
        print('Your classifier does not provide a show_most_informative_features() method.')
    accuracy = sentim_analyzer.evaluate(classifier, test_set)
    print('Accuracy:', accuracy)

    if save_analyzer == True:
        save_file(sentim_analyzer, 'sa_subjectivity.pickle')

    extr = [f.__name__ for f in sentim_analyzer.feat_extractors]
    output_markdown('results.md', Dataset='subjectivity', Classifier=type(classifier).__name__,
                    Instances=2000, Tokenizer=word_tokenizer.__class__.__name__,
                    Feats=extr, Accuracy=accuracy)

    return sentim_analyzer

def demo_sent_subjectivity(text):
    """
    Classify a single sentence as subjective or objective using a stored
    SentimentAnalyzer.

    :param text: a sentence whose subjectivity has to be classified.
    """
    from nltk.classify import NaiveBayesClassifier
    from nltk.tokenize import regexp
    word_tokenizer = regexp.WhitespaceTokenizer()
    try:
        sentim_analyzer = load('sa_subjectivity.pickle')
    except LookupError:
        print('Cannot find the sentiment analyzer you want to load.')
        print('Training a new one using NaiveBayesClassifier.')
        sentim_analyzer = demo_subjectivity(NaiveBayesClassifier.train, True)

    # Tokenize and convert to lower case
    tokenized_text = [word.lower() for word in word_tokenizer.tokenize(text)]
    print(sentim_analyzer.classify(tokenized_text))

def demo_liu_hu_lexicon(sentence, plot=False):
    """
    Basic example of sentiment classification using Liu and Hu opinion lexicon.
    This function simply counts the number of positive, negative and neutral words
    in the sentence and classifies it depending on which polarity is more represented.
    Words that do not appear in the lexicon are considered as neutral.

    :param sentence: a sentence whose polarity has to be classified.
    :param plot: if True, plot a visual representation of the sentence polarity.
    """
    from nltk.corpus import LazyCorpusLoader
    from nltk.corpus import OpinionLexiconCorpusReader
    from nltk.tokenize import treebank

    opinion_lexicon = LazyCorpusLoader('opinion_lexicon', OpinionLexiconCorpusReader,
                                       r'(\w+)\-words\.txt', encoding='ISO-8859-2')

    tokenizer = treebank.TreebankWordTokenizer()
    pos_words = 0
    neg_words = 0
    tokenized_sent = [word.lower() for word in tokenizer.tokenize(sentence)]

    x = list(range(len(tokenized_sent))) # x axis for the plot
    y = []

    for word in tokenized_sent:
        if word in opinion_lexicon.positive():
            pos_words += 1
            y.append(1) # positive
        elif word in opinion_lexicon.negative():
            neg_words += 1
            y.append(-1) # negative
        else:
            y.append(0) # neutral

    if pos_words > neg_words:
        print('Positive')
    elif pos_words < neg_words:
        print('Negative')
    elif pos_words == neg_words:
        print('Neutral')

    if plot == True:
        try:
            _show_plot(x, y, x_labels=tokenized_sent, y_labels=['Negative', 'Neutral', 'Positive'])
        except NameError:
            print("matplotlib not installed. Graph generation not available.")

def demo_vader(text):
    """
    Output polarity scores for a text using Vader approach.

    :param text: a text whose polarity has to be evaluated.
    """
    from vader import SentimentIntensityAnalyzer
    sia = SentimentIntensityAnalyzer()
    print(sia.polarity_scores(text))


if __name__ == '__main__':
    from nltk.classify import NaiveBayesClassifier, MaxentClassifier
    from nltk.classify.scikitlearn import SklearnClassifier
    from sklearn.svm import LinearSVC

    naive_bayes = NaiveBayesClassifier.train
    svm = SklearnClassifier(LinearSVC()).train
    maxent = MaxentClassifier.train

    # demo_tweets(naive_bayes)
    # demo_movie_reviews(svm)
    # demo_subjectivity(svm)
    demo_sent_subjectivity("she's an artist , but hasn't picked up a brush in a year . ")
    # demo_liu_hu_lexicon("This movie was actually neither that funny, nor super witty.", plot=True)
    # demo_vader("This movie was actually neither that funny, nor super witty.")
