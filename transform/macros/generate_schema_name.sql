{# Use the configured +schema name verbatim (bronze/staging/silver/gold) instead of
   dbt's default <target_schema>_<custom_schema> concatenation. This gives clean,
   medallion-style schema names in DuckDB. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
