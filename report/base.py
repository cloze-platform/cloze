"""
Base classes and interfaces for the report generation system.

This module defines the core abstractions that all report components,
renderers, and analyzers must follow.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
from llm_chat.extensions import db
from llm_chat.models import ChatWindow, Conversation, Message


class ReportComponent(ABC):
    """
    Abstract base class for all report components.

    A component represents a complete feature in the report (e.g., AI Summary,
    Statistics, NLP Analysis). Each component:
    - Loads its own data from the database
    - Performs necessary analysis
    - Returns structured data ready for rendering

    Components should NOT handle rendering - that's the renderer's job.
    """

    def __init__(self, window_id: int, config: Dict[str, Any] = None):
        """
        Initialize component with chat window ID and optional configuration.

        Args:
            window_id: ID of the ChatWindow to generate report for
            config: Optional configuration dictionary (from window.report_config)
        """
        self.window_id = window_id
        self.config = config or {}
        self.window = None
        self.conversations = []
        self.messages = []
        self._load_data()

    def _load_data(self):
        """Load common data needed by most components."""
        self.window = db.session.get(ChatWindow, self.window_id)
        if not self.window:
            raise ValueError(f"ChatWindow with id {self.window_id} not found")

        self.conversations = Conversation.query.filter_by(window_id=self.window_id).all()

        # Get all messages for all conversations
        for conv in self.conversations:
            self.messages.extend(Message.query.filter_by(conversation_id=conv.id).all())

    @abstractmethod
    def generate(self) -> Dict[str, Any]:
        """
        Generate the component's data.

        Returns:
            Dictionary containing the component's analyzed data, ready for rendering.
            The structure should be well-documented in each component's docstring.
        """
        pass

    def get_name(self) -> str:
        """Return the component's name (used for registry lookup)."""
        return self.__class__.__name__.replace('Component', '').lower()


class Renderer(ABC):
    """
    Abstract base class for renderers.

    Renderers convert structured data into output formats (HTML, PDF, JSON, etc.).
    They handle the presentation logic but don't do any data processing or analysis.
    """

    @abstractmethod
    def render_component(self, component_name: str, data: Dict[str, Any]) -> str:
        """
        Render a single component's data.

        Args:
            component_name: Name of the component (e.g., 'ai_summary')
            data: The component's generated data

        Returns:
            Rendered output as string
        """
        pass

    @abstractmethod
    def render_header(self, report_data: Dict[str, Any]) -> str:
        """Render the report header."""
        pass

    @abstractmethod
    def render_full_report(self, report_data: Dict[str, Any]) -> str:
        """
        Render the complete report.

        Args:
            report_data: Full report data including metadata and all components

        Returns:
            Complete rendered report as string
        """
        pass


class Analyzer(ABC):
    """
    Abstract base class for text analyzers.

    Analyzers are pure utility functions that take text input and return
    analysis results. They should:
    - Have no side effects
    - Not access the database
    - Be reusable across different components
    - Be easy to test in isolation
    """

    @abstractmethod
    def analyze(self, texts: List[str]) -> Dict[str, Any]:
        """
        Analyze the given texts.

        Args:
            texts: List of text strings to analyze

        Returns:
            Dictionary containing analysis results
        """
        pass
