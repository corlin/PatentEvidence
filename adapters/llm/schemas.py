from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class FeatureItemSchema(BaseModel):
    feature_code: str = Field(description="Feature identifier, e.g. F1, F2, F3")
    feature_type: Literal["preamble", "characterizing"] = Field(
        description="Preamble (known/shared) or characterizing portion (inventive point)"
    )
    feature_statement: str = Field(description="Accurate statement of the technical feature")
    source_paragraph_id: str = Field(description="Source paragraph identifier from document, e.g. 0005")
    citation_quote: str = Field(description="Exact quote from the technical disclosure")
    technical_problem: str | None = Field(default=None, description="Problem addressed by this feature")
    technical_effect: str | None = Field(default=None, description="Technical effect achieved")


class FeatureExtractionResultSchema(BaseModel):
    technical_field: str = Field(description="Identified technical field")
    technical_problem: str = Field(description="Core technical problem solved by the invention")
    features: list[FeatureItemSchema] = Field(description="List of extracted technical features")


class SearchStrategyResultSchema(BaseModel):
    keywords_zh: list[str] = Field(description="Expanded Chinese keywords and synonyms")
    keywords_en: list[str] = Field(description="Expanded English keywords and synonyms")
    cpc_classes: list[str] = Field(description="Recommended CPC classification symbols")
    ipc_classes: list[str] = Field(description="Recommended IPC classification symbols")
    boolean_query_cnipr: str = Field(description="Boolean query for CNIPR Chinese patent search")
    boolean_query_epo: str = Field(description="Boolean query for EPO Epoque patent search")
    boolean_query_uspto: str = Field(description="Boolean query for USPTO patent search")


class ClaimComparisonItemSchema(BaseModel):
    feature_id: str = Field(description="ID or code of the technical feature being compared")
    judgment: Literal["identical", "equivalent", "different"] = Field(
        description="identical (完全公开), equivalent (等同替代), or different (存在差异/未公开)"
    )
    citation_location: str = Field(
        description="Precise location in the reference document, e.g. 说明书[0035]段 或 权利要求1"
    )
    citation_quote: str = Field(
        description="Exact quote from the reference document text. Must be an exact substring, never fabricated."
    )
    reasoning: str = Field(
        description="Detailed legal and technical reasoning according to patent examination principles"
    )


class ComparisonMatrixResultSchema(BaseModel):
    comparisons: list[ClaimComparisonItemSchema] = Field(
        description="Itemized comparison result for each feature"
    )
    risk_level: Literal["high_novelty_risk", "high_inventive_risk", "clear_differentiation"] = Field(
        description="Overall patentability risk level based on All Elements Rule and Three-Step Test"
    )
    risk_reasoning: str = Field(
        description="Comprehensive patentability evaluation summary explaining the novelty and inventive step risk"
    )
