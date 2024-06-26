import React from 'react';
import './Message.css';

interface MessageProps {
  message: string;
  onClose: () => void;
}

const Message: React.FC<MessageProps> = ({ message, onClose }) => {
  return (
    <div className="message-container">
      <div className="message">
        <span>{message}</span>
        <button className="close-btn" onClick={onClose}>
          &times;
        </button>
      </div>
    </div>
  );
};

export default Message;
