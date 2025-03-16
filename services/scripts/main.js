import { bulk_apply } from "./bulk_apply.js";  // Import function

async function main() {
    try {
        var results = await bulk_apply();
        console.log("messagesdfd")
        console.log(results)
        results = results.messages;
        var messageContainer = document.getElementById("message-container");
        var alternateColor = false; 
        var messageIndex = 0; 
        var usersPerGroup = 4;
        var messages=[]
        results.forEach(function (result) {
            var useAlternateColor = alternateColor;
            if (messageIndex % usersPerGroup === 0) {
                alternateColor = !alternateColor;
            }

            var userContainer = document.createElement("div");
            userContainer.className = `p-4 rounded-lg shadow ${useAlternateColor ? 'bg-gray-200' : 'bg-gray-100'}`;

            result.forEach(function (messageText) {
                var messageDiv = document.createElement("div");
                messageDiv.className = "p-3 rounded text-white font-semibold mb-2";

                if (messageText.includes('BLOCKED_APPROVE')) {
                    messageDiv.classList.add("bg-yellow-500");
                } else if (messageText.includes('Not Alloted') || messageText.includes('BLOCK_FAILED')) {
                    messageDiv.classList.add("bg-red-500");
                } else if (messageText.includes('Alloted')) {
                    messageDiv.classList.add("bg-green-500");
                } else {
                    messageDiv.classList.add("bg-gray-300", "text-gray-800");
                }

                messageDiv.innerText = messageText;
                userContainer.appendChild(messageDiv);
            });

            messageContainer.appendChild(userContainer);
            messageIndex++;
        });
    } catch (error) {
        console.error(error);
    }
}
main()