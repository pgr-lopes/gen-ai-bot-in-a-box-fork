# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
from botbuilder.core import ConversationState, TurnContext, UserState, CardFactory
from botbuilder.schema import ChannelAccount, Activity, ActivityTypes
from botbuilder.dialogs import Dialog
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
import semantic_kernel as sk
from semantic_kernel.connectors.ai.open_ai import (
    AzureAISearchDataSource,
    AzureChatCompletion,
    AzureChatPromptExecutionSettings,
    ExtraBody,
    ApiKeyAuthentication
)
from semantic_kernel.connectors.memory.azure_cognitive_search.azure_ai_search_settings import AzureAISearchSettings
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import KernelArguments
from semantic_kernel.prompt_template import InputVariable, PromptTemplateConfig
    
from data_models import ConversationData, ConversationTurn
from .state_management_bot import StateManagementBot
from utils import get_citations_card, replace_citations

class SemanticKernelBot(StateManagementBot):

    def __init__(self, conversation_state: ConversationState, user_state: UserState, aoai_client: AzureOpenAI, dialog: Dialog):
        super().__init__(conversation_state, user_state, dialog)
        self._aoai_client = aoai_client

    # Modify onMembersAdded as needed
    async def on_members_added_activity(self, members_added: list[ChannelAccount], turn_context: TurnContext):
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity("Hello and welcome to the Semantic Kernel Bot Python!")

    async def on_message_activity(self, turn_context: TurnContext):
        # Load conversation state
        conversation_data = await self.conversation_data_accessor.get(turn_context, ConversationData([]))

        # Add user message to history
        conversation_data.add_turn("user", turn_context.activity.text)
        
        # Run logic to obtain response
        kernel = sk.Kernel()

        az_source = AzureAISearchDataSource(parameters={
            "endpoint": os.getenv("AZURE_SEARCH_API_ENDPOINT"),
            "index_name": os.getenv("AZURE_SEARCH_INDEX"),
            "query_type": "simple",
        })
        extra = ExtraBody(data_sources=[az_source])
        req_settings = AzureChatPromptExecutionSettings(service_id="default", extra_body=extra)

        chat_service = AzureChatCompletion(
            service_id="chat-gpt",
            ad_token_provider=get_bearer_token_provider(
                DefaultAzureCredential(), 
                "https://cognitiveservices.azure.com/.default"
            ),
            endpoint=os.getenv("AZURE_OPENAI_API_ENDPOINT"),
            deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
        )
        kernel.add_service(chat_service)

        prompt_template_config = PromptTemplateConfig(
            template="{{$chat_history}}",
            name="chat",
            template_format="semantic-kernel",
            input_variables=[
                InputVariable(name="chat_history", description="The history of the conversation", is_required=True)
            ],
            execution_settings={"default": req_settings}
        )

        history = ChatHistory()

        for message in conversation_data.history:
            if message.role == "user":
                history.add_user_message(message.content)
            else:
                history.add_assistant_message(message.content)

        chat_function = kernel.add_function(
            plugin_name="ChatBot", function_name="Chat", prompt_template_config=prompt_template_config
        )

        arguments = KernelArguments(settings=req_settings)

        arguments["chat_history"] = history
        answer = await kernel.invoke(
            function=chat_function,
            arguments=arguments,
        )

        response = str(answer)
        response = replace_citations(response)

        # Add assistant message to history
        conversation_data.add_turn("assistant", response)

        # Respond back to user
        await turn_context.send_activity(response)

        # Send citations if they exist
        if 'citations' in answer.get_inner_content().choices[0].message.context and len(answer.get_inner_content().choices[0].message.context['citations']) > 0:
            citations = answer.get_inner_content().choices[0].message.context['citations']
            await turn_context.send_activity(get_citations_card(citations))
