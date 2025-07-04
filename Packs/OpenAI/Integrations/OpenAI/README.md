The OpenAI API can be applied to virtually any task that involves understanding or generating natural language or code. We offer a spectrum of models with different levels of power suitable for different tasks, as well as the ability to fine-tune your own custom models. These models can be used for everything from content generation to semantic search and classification.
This integration was integrated and tested with version 1 of OpenAI

## Configure OpenAI in Cortex

| **Parameter** | **Required** |
| --- | --- |
| OpenAI API URL(e.g. https://api.openai.com/) | True |
| API Key | True |
| Trust any certificate (not secure) | False |
| Use system proxy settings | False |

## Commands

You can execute these commands from the CLI, as part of an automation, or in a playbook.
After you successfully execute a command, a DBot message appears in the War Room with the command details.

### openai-completions

***
Enter an instruction and watch the API respond with a completion that attempts to match the context or pattern you provided.

#### Base Command

`openai-completions`

#### Input

| **Argument Name** | **Description** | **Required** |
| --- | --- | --- |
| prompt | Instruction. | Required |
| model | The model which will generate the completion. Some models are suitable for natural language tasks, others specialize in code. Possible values are: text-davinci-003, text-curie-001, text-babbage-001, text-ada-001, code-davinci-002, code-cushman-001. Default is text-davinci-003. | Optional |
| temperature | Controls randomness: Lowering results in less random completions. Default is 0.7. | Optional |
| max_tokens | The maximum number of token to generate. Default is 256. | Optional |
| top_p | Controls Diversity via nucleus sampling: 0.5 means half of all likihood-weighted options are considered. Default is 1. | Optional |
| frequency_penalty | How much to penalize new tokens based on their existing frequency in the text so far. Decreases the model's likelihood to repeat the same line verbatim. Default is 0. | Optional |
| presence_penalty | How much to penalize new tokens based on whether they appear in the text so far. Increases the model's likelihood to talk about new topics. Default is 0. | Optional |

#### Context Output

| **Path** | **Type** | **Description** |
| --- |----------| --- |
| OpenAI.Completions.id | String   | Id of the returned completion. |
| OpenAI.Completions.model | String  | The model which will generate the completion. |
| OpenAI.Completions.text | String  |  Completed text generated by OpenAI? |

#### Command example

```!openai-completions prompt="Give me some characteristics of a phishing email" model="text-davinci-003" temperature="0.7" max_tokens="256" top_p="1" frequency_penalty="0" presence_penalty="0"```

#### Context Example

```json
{
    "OpenAI": {
        "Completions": {
            "id": "cmpl-6K7q5vYUr6SzEbAOb6LoQRF7rp3KN",
            "model": "text-davinci-003",
            "text": "1. Unsolicited email from an unknown source2. Asks for confidential information such as passwords, bank account details, or credit card numbers3. Contains spelling and grammar errors4. Contains urgent language, threats, or a false sense of urgency5. Uses generic greetings like \"Dear Customer\" instead of your name6. Links to a suspicious website that looks legitimate7. Uses a spoofed email address that appears to be from a trusted source"
        }
    }
}
```
