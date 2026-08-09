from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.models.generation_profiles import (
    GenerationProfileResponse,
    TemplateFieldsUpdate,
)
from app.services.generation_profile_service import GenerationProfileService


router = APIRouter(
    prefix="/projects/{project_id}/generation-profile",
    tags=["generation profile"],
)


def get_service() -> GenerationProfileService:
    return GenerationProfileService()


@router.get("", response_model=GenerationProfileResponse)
def get_generation_profile(
    project_id: UUID,
    service: GenerationProfileService = Depends(get_service),
):
    profile = service.get(project_id)
    return GenerationProfileResponse(
        project_id=profile.project_id,
        generation_mode=profile.generation_mode,
        writer_strategy=profile.writer_strategy,
        template_conversion_status=profile.template_conversion_status,
        template_conversion_report=(profile.template_conversion_report or {}),
        historical_case_mode=profile.historical_case_mode,
        template_descriptor=profile.template_descriptor,
        template_filename=profile.template_filename,
        template_field_values=profile.template_field_values,
    )


@router.put("/template-fields", response_model=GenerationProfileResponse)
def update_template_fields(
    project_id: UUID,
    payload: TemplateFieldsUpdate,
    service: GenerationProfileService = Depends(get_service),
):
    try:
        profile = service.update_template_fields(project_id, payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return GenerationProfileResponse(
        project_id=profile.project_id,
        generation_mode=profile.generation_mode,
        writer_strategy=profile.writer_strategy,
        template_conversion_status=profile.template_conversion_status,
        template_conversion_report=(profile.template_conversion_report or {}),
        historical_case_mode=profile.historical_case_mode,
        template_descriptor=profile.template_descriptor,
        template_filename=profile.template_filename,
        template_field_values=profile.template_field_values,
    )
