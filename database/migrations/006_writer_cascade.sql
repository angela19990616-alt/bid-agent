ALTER TABLE section_requirements
    DROP CONSTRAINT section_requirements_requirement_id_fkey;

ALTER TABLE section_requirements
    ADD CONSTRAINT section_requirements_requirement_id_fkey
    FOREIGN KEY (requirement_id) REFERENCES requirements(id)
    ON DELETE CASCADE;
