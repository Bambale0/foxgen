# Reference memory Telegram UI contract

Reference screens expose `📚 Память реф` next to `🔄 Перезагрузить`.

The memory browser uses one replaceable control message. When the library contains images, the control is a Telegram photo preview with an inline keyboard. Navigating deletes/replaces the previous control instead of accumulating a gallery of stale keyboards.

The browser shows selected count versus the current model/scenario capacity, private storage usage, previous/next navigation, select/unselect, add photo, optional save-current-draft images, delete confirmation, apply selection and back.

Back returns to the originating reference screen without applying browser selection. Apply replaces only the durable-reference portion of the generation draft; existing temporary inputs stay in their original order.
