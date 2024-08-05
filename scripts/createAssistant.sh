set -e

echo "Loading azd .env file from current environment..."

while IFS='=' read -r key value; do
    value=$(echo "$value" | sed 's/^"//' | sed 's/"$//')
    export "$key=$value"
done <<EOF
$(azd env get-values)
EOF

OAUTH_TOKEN=$(az account get-access-token --scope https://cognitiveservices.azure.com/.default --query accessToken -o tsv)
AOAI_ASSISTANT_NAME="assistant_in_a_box"
ASSISTANT_ID=$(curl "$AI_SERVICES_ENDPOINT/openai/assistants?api-version=2024-02-15-preview" \
  -H "Authorization: Bearer $OAUTH_TOKEN" | \
  jq -r '[.data[] | select( .name == "'$AOAI_ASSISTANT_NAME'")][0] | .id') 
if [ "$ASSISTANT_ID" == "null" ]; then    
    ASSISTANT_ID=
else
    ASSISTANT_ID=/$ASSISTANT_ID
fi   

echo '{
    "name":"'$AOAI_ASSISTANT_NAME'",
    "model":"gpt-4",
    "instructions":"",
    "tools": '$(cat ./assistants_tools/*.json | jq -s)',
    "file_ids":[],
    "metadata":{}
  }' > tmp.json
curl "$AI_SERVICES_ENDPOINT/openai/assistants$ASSISTANT_ID?api-version=2024-02-15-preview" \
  -H "Authorization: Bearer $OAUTH_TOKEN" \
  -H 'content-type: application/json' \
  -d @tmp.json \
  --fail-with-body
rm tmp.json

ASSISTANT_ID=$(curl "$AI_SERVICES_ENDPOINT/openai/assistants?api-version=2024-02-15-preview" \
  -H "Authorization: Bearer $OAUTH_TOKEN"|\
  jq -r '[.data[] | select( .name == "'$AOAI_ASSISTANT_NAME'")][0] | .id')

az webapp config appsettings set -g $AZURE_RESOURCE_GROUP_NAME -n $APP_NAME --settings AOAI_ASSISTANT_ID=$ASSISTANT_ID APP_URL=$APP_HOSTNAME

azd env set AZURE_ASSISTANT_ID $ASSISTANT_ID