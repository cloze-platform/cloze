"""
Co-occurrence Analysis

Analyzes word co-occurrences within sentences to identify patterns and
relationships in text. Creates a network graph showing which words appear
together frequently.
"""

from typing import List, Dict, Any
from collections import Counter
import base64
from io import BytesIO

from report.base import Analyzer

# Optional dependencies for visualization
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend for server use
    import matplotlib.pyplot as plt
    import networkx as nx
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False

try:
    from nltk.corpus import stopwords
    from nltk.tokenize import word_tokenize
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False


class CooccurrenceAnalyzer(Analyzer):
    """Analyzes word co-occurrences in text to identify patterns and relationships."""

    def __init__(self, min_cooccurrence: int = 2, top_n_words: int = 20,
                 graph_style: str = 'product'):
        """
        Initialize the co-occurrence analyzer.

        Args:
            min_cooccurrence: Minimum times words must co-occur to be included
            top_n_words: Maximum number of words to include in the graph
            graph_style: 'product' (colorful, casual) or 'academic' (grayscale, serif, high DPI)
        """
        self.min_cooccurrence = min_cooccurrence
        self.top_n_words = top_n_words
        self.graph_style = graph_style

        # Check dependencies
        if not NLTK_AVAILABLE:
            raise ImportError("NLTK is required for co-occurrence analysis. Install with: pip install nltk")

        # Ensure NLTK data is available
        try:
            stopwords.words('english')
        except LookupError:
            import nltk
            nltk.download('stopwords', quiet=True)

        try:
            word_tokenize("test")
        except LookupError:
            import nltk
            nltk.download('punkt', quiet=True)
            nltk.download('punkt_tab', quiet=True)

    def analyze(self, texts: List[str]) -> Dict[str, Any]:
        """
        Analyze word co-occurrences in the given texts.

        Args:
            texts: List of text strings to analyze

        Returns:
            Dict containing:
                - cooccurrence_matrix: Dictionary of word pairs and their frequencies
                - top_words: Most frequent words
                - total_unique_words: Number of unique words after filtering
                - graph_image: Base64-encoded PNG of the co-occurrence graph (if available)
                - has_visualization: Whether visualization was generated
        """
        if not texts:
            return self._empty_result()

        # Combine all texts
        combined_text = ' '.join(texts)

        # Clean and tokenize
        cleaned_text = self._clean_text(combined_text)
        tokenized_sentences = self._tokenize_sentences(cleaned_text)

        if not tokenized_sentences:
            return self._empty_result()

        # Create co-occurrence matrix
        cooccurrence_matrix = self._create_cooccurrence_matrix(tokenized_sentences)

        # Get word frequencies
        all_words = [word for sentence in tokenized_sentences for word in sentence]
        word_freq = Counter(all_words)
        top_words = word_freq.most_common(self.top_n_words)

        # Generate visualization if available
        graph_image = None
        has_visualization = False

        if VISUALIZATION_AVAILABLE and cooccurrence_matrix:
            try:
                graph_image = self._create_graph(
                    cooccurrence_matrix,
                    tokenized_sentences
                )
                has_visualization = True
            except Exception as e:
                print(f"Warning: Could not generate co-occurrence graph: {e}")

        return {
            "cooccurrence_matrix": cooccurrence_matrix,
            "top_words": [{"word": word, "count": count} for word, count in top_words],
            "total_unique_words": len(word_freq),
            "total_sentences": len(tokenized_sentences),
            "graph_image": graph_image,
            "has_visualization": has_visualization
        }

    def _clean_text(self, text: str) -> str:
        """Remove unnecessary punctuation."""
        text = text.replace(",", "")
        return text

    def _tokenize_sentences(self, cleaned_text: str) -> List[List[str]]:
        """
        Tokenize text into sentences and words, removing stopwords.

        Args:
            cleaned_text: Pre-cleaned text

        Returns:
            List of sentences, where each sentence is a list of words
        """
        # Split by periods
        sentences = cleaned_text.lower().split(".")

        tokenized_sentences = []
        stop_words = set(stopwords.words("english"))

        for sentence in sentences:
            if sentence.strip():
                words = word_tokenize(sentence)
                # Filter stopwords and keep only alphabetic words
                cleaned_words = [
                    word for word in words
                    if word not in stop_words and word.isalpha()
                ]
                if cleaned_words:  # Only add non-empty sentences
                    tokenized_sentences.append(cleaned_words)

        return tokenized_sentences

    def _create_cooccurrence_matrix(
        self,
        tokenized_sentences: List[List[str]]
    ) -> Dict[str, Dict[str, int]]:
        """
        Create a co-occurrence matrix from tokenized sentences.

        Args:
            tokenized_sentences: List of sentences with tokenized words

        Returns:
            Nested dictionary: {word1: {word2: count, word3: count, ...}, ...}
        """
        cooccurrences = {}

        for sentence in tokenized_sentences:
            for word in sentence:
                if word not in cooccurrences:
                    cooccurrences[word] = {}

                for other_word in sentence:
                    if other_word != word:
                        if other_word not in cooccurrences[word]:
                            cooccurrences[word][other_word] = 0
                        cooccurrences[word][other_word] += 1

        # Filter by minimum co-occurrence threshold
        filtered_cooccurrences = {}
        for word, related_words in cooccurrences.items():
            filtered_related = {
                other: count
                for other, count in related_words.items()
                if count >= self.min_cooccurrence
            }
            if filtered_related:
                filtered_cooccurrences[word] = filtered_related

        return filtered_cooccurrences

    def _create_graph(
        self,
        cooccurrence_dict: Dict[str, Dict[str, int]],
        tokenized_sentences: List[List[str]]
    ) -> str:
        """
        Create a network graph visualization of word co-occurrences.

        Args:
            cooccurrence_dict: Co-occurrence matrix
            tokenized_sentences: Tokenized sentences for word frequency

        Returns:
            Base64-encoded PNG image string
        """
        if not VISUALIZATION_AVAILABLE:
            return None

        # Create graph
        G = nx.Graph()

        # Add edges with weights based on co-occurrence frequency
        for word, related_words in cooccurrence_dict.items():
            for cooccurring_word, count in related_words.items():
                # Square the count for stronger proximity effect
                proximity = count ** 2
                G.add_edge(word, cooccurring_word, weight=proximity)

        if len(G.nodes) == 0:
            return None

        # Calculate word frequencies for node sizing
        all_words = [word for sentence in tokenized_sentences for word in sentence]
        word_freq = Counter(all_words)

        # Node sizes based on word frequency
        node_sizes = [word_freq.get(node, 1) * 1500 for node in G.nodes]

        # Create layout
        pos = nx.spring_layout(G, weight="weight", k=0.5, iterations=50)

        if self.graph_style == 'academic':
            # Academic style: grayscale, serif fonts, high DPI
            original_params = plt.rcParams.copy()
            plt.rcParams.update({
                'font.family': 'serif',
                'font.serif': ['Times New Roman', 'Georgia', 'DejaVu Serif'],
            })

            plt.figure(figsize=(10, 7), facecolor='white')
            plt.clf()

            nx.draw(
                G, pos,
                with_labels=True,
                node_size=node_sizes,
                node_color="#cccccc",
                edge_color="#888888",
                font_size=9,
                font_weight="normal",
                font_family="serif",
                alpha=0.9,
                linewidths=1.0,
                edgecolors="#555555",
            )

            plt.title("Word Co-occurrence Network",
                      fontsize=12, fontfamily='serif', fontweight='normal')
            plt.axis('off')
            plt.tight_layout()

            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=200, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
            plt.close()

            # Restore original params
            plt.rcParams.update(original_params)

            return image_base64
        else:
            # Product style: colorful, casual (default)
            plt.figure(figsize=(12, 8))
            plt.clf()

            nx.draw(
                G, pos,
                with_labels=True,
                node_size=node_sizes,
                node_color="skyblue",
                edge_color="gray",
                font_size=10,
                font_weight="bold",
                alpha=0.9
            )

            plt.title("Word Co-occurrence Network", fontsize=14, fontweight='bold')
            plt.axis('off')
            plt.tight_layout()

            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
            plt.close()

            return image_base64

    def _empty_result(self) -> Dict[str, Any]:
        """Return empty result structure."""
        return {
            "cooccurrence_matrix": {},
            "top_words": [],
            "total_unique_words": 0,
            "total_sentences": 0,
            "graph_image": None,
            "has_visualization": False
        }
